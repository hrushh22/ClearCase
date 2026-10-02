"""Keep the SQLite database across restarts on hosts with a temporary disk (e.g. Hugging Face Spaces).

Off unless HF_TOKEN and PERSIST_DATASET are set. Then:
  * on startup, the last saved database is downloaded from the PRIVATE dataset repo (if the local file is missing)
  * every 2 minutes, and after each sync, a consistent copy is uploaded when it changed
The dataset must be private: it holds case data.
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import threading
import time
import traceback
from pathlib import Path

from .config import OCR_CACHE_DIR, database_path, env

FILENAME = "clearcase.db"
_last_hash: str | None = None
_lock = threading.Lock()


def enabled() -> bool:
    return bool(env("HF_TOKEN") and env("PERSIST_DATASET"))


def restore() -> str:
    """Database + OCR cache from the private dataset. With the OCR cache present the server never has to run
    OCR for documents it has seen before (OCR is the most memory-hungry step on small hosts)."""
    if not enabled():
        return "off"
    path = database_path()
    out = []
    try:
        from huggingface_hub import hf_hub_download, snapshot_download

        if not path.exists():
            src = hf_hub_download(env("PERSIST_DATASET"), FILENAME, repo_type="dataset", token=env("HF_TOKEN"))
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, path)  # contents only: the download cache is read-only
            out.append("database restored")
        snap = snapshot_download(env("PERSIST_DATASET"), repo_type="dataset", token=env("HF_TOKEN"), allow_patterns=["ocr/*.json"])
        n = 0
        for f in (Path(snap) / "ocr").glob("*.json"):
            dst = OCR_CACHE_DIR / f.name
            if not dst.exists():
                shutil.copyfile(f, dst)
                n += 1
        out.append(f"{n} OCR files restored")
    except Exception as e:  # first boot: nothing saved yet
        out.append(f"nothing more to restore ({type(e).__name__})")
    return "; ".join(out)


def backup_ocr() -> str:
    """Upload OCR results the dataset does not have yet."""
    if not enabled():
        return "off"
    from huggingface_hub import HfApi

    api = HfApi(token=env("HF_TOKEN"))
    have = {f for f in api.list_repo_files(env("PERSIST_DATASET"), repo_type="dataset") if f.startswith("ocr/")}
    new = [f for f in OCR_CACHE_DIR.glob("*.json") if f"ocr/{f.name}" not in have]
    if new:
        api.upload_folder(folder_path=str(OCR_CACHE_DIR), path_in_repo="ocr", repo_id=env("PERSIST_DATASET"), repo_type="dataset",
                          allow_patterns=[f.name for f in new], commit_message="ClearCase OCR cache")
    return f"{len(new)} OCR files uploaded"


def backup(force: bool = False) -> str:
    global _last_hash
    if not enabled() or not database_path().exists():
        return "off"
    with _lock:
        tmp = Path(tempfile.mkdtemp()) / FILENAME
        src = sqlite3.connect(database_path())
        dst = sqlite3.connect(tmp)
        src.backup(dst)  # consistent snapshot even while the app writes (WAL)
        src.close(), dst.close()
        h = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if h == _last_hash and not force:
            return "unchanged"
        from huggingface_hub import HfApi

        api = HfApi(token=env("HF_TOKEN"))
        api.create_repo(env("PERSIST_DATASET"), repo_type="dataset", private=True, exist_ok=True)
        api.upload_file(path_or_fileobj=str(tmp), path_in_repo=FILENAME, repo_id=env("PERSIST_DATASET"), repo_type="dataset",
                        commit_message="ClearCase state backup")
        _last_hash = h
    try:
        backup_ocr()
    except Exception:
        traceback.print_exc()
    return "uploaded"


def start_background(interval: int = 120) -> None:
    if not enabled():
        return

    def loop():
        while True:
            time.sleep(interval)
            try:
                backup()
            except Exception:
                traceback.print_exc()

    threading.Thread(target=loop, daemon=True).start()
