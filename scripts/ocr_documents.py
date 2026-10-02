"""Pre-warm the per-page text/OCR cache for every PDF in a folder (or the documents in our DB).

Usage: python scripts/ocr_documents.py ["path/to/Sapini documents"]
The cache is keyed by file SHA-256, so documents later downloaded from Clio reuse it.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import ROOT  # noqa: E402
from app.documents import extract_pages, sha256_file  # noqa: E402


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "Sapini Case Materials" / "Sapini documents"
    pdfs = sorted(folder.rglob("*.pdf"), key=lambda p: p.stat().st_size)
    for p in pdfs:
        t = time.time()
        pages = extract_pages(p, sha256_file(p),
                              progress=lambda i, n: print(f"  {p.name}: {i}/{n}", flush=True) if i % 25 == 0 else None)
        ocr = sum(1 for pg in pages if pg["method"] == "ocr")
        print(f"{p.name}: {len(pages)} pages ({ocr} OCR) in {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
