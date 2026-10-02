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

from .config import database_path, env

FILENAME = "clearcase.db"
_last_hash: str | None = None
_lock = threading.Lock()


def enabled() -> bool:
    return bool(env("HF_TOKEN") and env("PERSIST_DATASET"))


def restore() -> str:
    if not enabled():
        return "off"
    path = database_path()
    if path.exists():
        return "local database present"
    try:
        from huggingface_hub import hf_hub_download

        src = hf_hub_download(env("PERSIST_DATASET"), FILENAME, repo_type="dataset", token=env("HF_TOKEN"))
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, path)
        return "restored"
    except Exception as e:  # first boot: nothing saved yet
        return f"nothing to restore ({type(e).__name__})"


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
