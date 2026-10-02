"""Sync the matter from Clio (GET only) and rebuild the digest if anything changed.

Usage: python scripts/sync.py [--force]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import digest  # noqa: E402


def main() -> None:
    digest._progress = lambda msg: (digest._status.__setitem__("step", msg), print("  ..", msg, flush=True))
    res = digest.run_pipeline(force="--force" in sys.argv)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
