"""Document Agent, code half: per-page text + word/line boxes for every PDF.

Text pages use the PDF text layer (PyMuPDF words). Scanned pages are rendered and
OCR'd locally with RapidOCR (ONNX, no system install), which returns line boxes.
Results are cached on disk by file SHA-256, so a document is only OCR'd once.

All boxes are stored in PDF points ([x0, y0, x1, y1], origin top-left) so the
frontend can overlay them on pdf.js regardless of render scale.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pymupdf

from .config import OCR_CACHE_DIR

OCR_DPI = 150
MIN_TEXT_CHARS = 60
OCR_VERSION = "rapidocr-v1"

_ocr_engine = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_document(name: str, folder: str | None) -> str:
    """Folder name is a strong hint; file name breaks ties."""
    s = f"{folder or ''} {name}".lower()
    rules = [
        ("intake", "intake"), ("retainer", "intake"), ("pleading", "pleading"),
        ("discovery", "discovery"), ("subpoena", "discovery"), ("medical record", "medical_record"),
        ("medical-records", "medical_record"), ("bill", "bill"), ("lien", "bill"),
        ("correspondence", "correspondence"), ("letter", "correspondence"), ("expert", "expert_report"),
        ("ime", "expert_report"), ("insurance", "insurance"), ("settlement", "settlement"),
    ]
    for key, kind in rules:
        if key in s:
            return kind
    return "other"


def _engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _ocr_page(page: pymupdf.Page) -> tuple[str, list[dict[str, Any]]]:
    import numpy as np

    pix = page.get_pixmap(dpi=OCR_DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3]
    result, _ = _engine()(img)
    scale = 72.0 / OCR_DPI
    words = []
    for box, text, score in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        words.append({"t": text, "b": [round(min(xs) * scale, 1), round(min(ys) * scale, 1),
                                       round(max(xs) * scale, 1), round(max(ys) * scale, 1)],
                      "c": round(float(score), 3)})
    # reading order: top-to-bottom, then left-to-right
    words.sort(key=lambda w: (round(w["b"][1] / 6), w["b"][0]))
    return "\n".join(w["t"] for w in words), words


def _text_page(page: pymupdf.Page) -> tuple[str, list[dict[str, Any]]]:
    words = [{"t": w[4], "b": [round(w[0], 1), round(w[1], 1), round(w[2], 1), round(w[3], 1)]}
             for w in page.get_text("words")]
    return page.get_text(), words


def extract_pages(path: Path, sha: str | None = None, progress=None) -> list[dict[str, Any]]:
    """Return [{page, text, words, method, width, height}] for every page, cached by SHA."""
    sha = sha or sha256_file(path)
    cache = OCR_CACHE_DIR / f"{sha}.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("version") == OCR_VERSION:
            return data["pages"]
    pages = []
    doc = pymupdf.open(path)
    for i, page in enumerate(doc):
        text = page.get_text()
        if len(text.strip()) >= MIN_TEXT_CHARS:
            text, words = _text_page(page)
            method = "text"
        else:
            text, words = _ocr_page(page)
            method = "ocr"
        pages.append({"page": i + 1, "text": text, "words": words, "method": method,
                      "width": page.rect.width, "height": page.rect.height})
        if progress:
            progress(i + 1, doc.page_count)
    cache.write_text(json.dumps({"version": OCR_VERSION, "pages": pages}), encoding="utf-8")
    return pages


# ---------------------------------------------------------------- highlighting

_norm_re = re.compile(r"[^a-z0-9]")


def norm_compact(s: str) -> str:
    """Lowercase, drop everything but letters/digits. OCR often loses spaces, so we match without them."""
    return _norm_re.sub("", (s or "").lower())


def locate_snippet(words: list[dict[str, Any]], snippet: str, min_score: float = 80.0) -> dict[str, Any]:
    """Find the boxes covering `snippet` on a page.

    Works for both PDF words and OCR lines: concatenate normalized tokens, keep an
    offset map back to each token, then exact-match or fuzzy-align the snippet.
    Returns {"bboxes": [...], "match": "exact"|"fuzzy"|"none", "score": float}.
    """
    target = norm_compact(snippet)
    if not target or not words:
        return {"bboxes": [], "match": "none", "score": 0.0}
    hay_parts, owners = [], []
    for idx, w in enumerate(words):
        n = norm_compact(w["t"])
        hay_parts.append(n)
        owners.extend([idx] * len(n))
    hay = "".join(hay_parts)
    start = hay.find(target)
    match, score = "exact", 100.0
    if start < 0:
        from rapidfuzz import fuzz

        if len(target) > len(hay):
            return {"bboxes": [], "match": "none", "score": 0.0}
        al = fuzz.partial_ratio_alignment(target, hay, score_cutoff=min_score)
        if not al:
            return {"bboxes": [], "match": "none", "score": 0.0}
        start, end, match, score = al.dest_start, al.dest_end, "fuzzy", float(al.score)
    else:
        end = start + len(target)
    hit = sorted(set(owners[start:max(start + 1, end)]))
    return {"bboxes": _merge_boxes([words[i]["b"] for i in hit]), "match": match, "score": round(score, 1)}


def _merge_boxes(boxes: list[list[float]]) -> list[list[float]]:
    """Merge word boxes on the same line into one rectangle per line."""
    lines: list[list[float]] = []
    for b in sorted(boxes, key=lambda b: (b[1], b[0])):
        if lines and abs(lines[-1][1] - b[1]) < 4 and b[0] - lines[-1][2] < 40:
            last = lines[-1]
            lines[-1] = [min(last[0], b[0]), min(last[1], b[1]), max(last[2], b[2]), max(last[3], b[3])]
        else:
            lines.append(list(b))
    return lines


def find_page_for_quote(pages: list[dict[str, Any]], quote: str, hint: int | None = None) -> tuple[int | None, dict]:
    """Search the hinted page first, then the whole document."""
    order = list(range(len(pages)))
    if hint and 1 <= hint <= len(pages):
        order.remove(hint - 1)
        order.insert(0, hint - 1)
    best: tuple[int | None, dict] = (None, {"bboxes": [], "match": "none", "score": 0.0})
    for i in order:
        res = locate_snippet(pages[i]["words"], quote)
        if res["match"] == "exact":
            return i + 1, res
        if res["score"] > best[1]["score"]:
            best = (i + 1, res)
    return best
