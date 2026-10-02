"""Shared helpers: facts with their 'known at' date, source refs, body regions, dates in text."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from functools import lru_cache

from .. import db
from ..agents.verifier import VISIBLE

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

REGIONS: list[tuple[str, str, str]] = [  # (key, label, regex)
    ("head", "Head / brain", r"\bhead\b|concussi|\bbrain\b|\btbi\b|skull|headache|post-?concussive"),
    ("neck", "Neck / cervical spine", r"cervical|\bneck\b|\bC[1-7](?:\s*-\s*C?[1-7])?\b"),
    ("shoulder", "Shoulder", r"shoulder|labral|labrum|rotator cuff|glenoid|acromi|subacromial|biceps tendon"),
    ("arm", "Arm / elbow / wrist / hand", r"\barms?\b|elbow|wrist|\bhands?\b|forearm|carpal|radial (?:nerve|peripheral|sensory)|upper extremit"),
    ("upper_back", "Upper back / thoracic", r"thoracic|upper back|\bT(?:[1-9]|1[0-2])\b"),
    ("lower_back", "Lower back / lumbar", r"lumbar|low(?:er)? back|\bL[1-5](?:\s*-\s*S?[1-5])?\b|sacr|lower extremit"),
    ("hip", "Hip / pelvis", r"\bhips?\b|pelvi"),
    ("knee", "Knee", r"\bknees?\b|menisc|patell"),
    ("leg_foot", "Leg / ankle / foot", r"ankle|\bfoot\b|\bfeet\b|\blegs?\b|tibia|fibula|talus|heel"),
]
REGION_LABEL = {k: label for k, label, _ in REGIONS}


@lru_cache(maxsize=20000)
def _regions_cached(text: str) -> tuple:
    return tuple(_regions(text))


def regions_in(text: str) -> list[tuple[str, str | None]]:
    """[(region_key, side)] mentioned in text. Side only when stated next to it; never guessed."""
    return list(_regions_cached(text or ""))


def _regions(text: str) -> list[tuple[str, str | None]]:
    out = []
    t = text or ""
    for key, _, rx in REGIONS:
        for m in re.finditer(rx, t, re.I):
            window = t[max(0, m.start() - 25):m.end() + 10].lower()
            side = "bilateral" if re.search(r"bilateral|both", window) else \
                "left" if re.search(r"\bleft\b|\blt\b", window) else "right" if re.search(r"\bright\b|\brt\b", window) else None
            if (key, side) not in out:
                out.append((key, side))
    return out


MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def dates_in(text: str) -> list[str]:
    """Explicit calendar dates written in text, as YYYY-MM-DD."""
    out = []
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text or ""):
        out.append(m.group(0))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text or ""):
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.append(f"{y:04d}-{mo:02d}-{d:02d}")
    for m in re.finditer(rf"\b({MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", text or "", re.I):
        mo = MONTHS.split("|").index(m.group(1).lower()) + 1
        out.append(f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}")
    return out


def amounts_in(text: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"\$\s?([0-9][0-9,]*(?:\.\d+)?)", text or "")]


def src(f: dict) -> dict:
    return {"fact_id": f.get("fact_id"), "source_type": f["source_type"], "source_id": f["source_id"], "page": f.get("page"),
            "quote": f.get("quote"), "date": f.get("date") or f.get("known_at"), "text": f.get("text")}


def load_facts(as_of: str | None = None) -> list[dict]:
    """Visible (verifier-passed) facts, each with `known_at`: the date the file first held it.

    known_at = the fact's own date if stated, else its source's date (note/email date, document received date).
    With `as_of`, only facts the file held on that date are returned (Time Travel).
    """
    rows = db.query(f"SELECT * FROM facts WHERE verify_status IN ({','.join('?' * len(VISIBLE))})", VISIBLE)
    src_dates = {(r["source_type"], r["source_id"]): r["date"] for r in db.query("SELECT source_type, source_id, date FROM sources")}
    doc_dates = {r["id"]: (r["received_at"] or "")[:10] or None for r in db.query("SELECT id, received_at FROM documents")}
    out = []
    for f in rows:
        f["bbox"] = json.loads(f.pop("bbox_json") or "[]")
        sd = doc_dates.get(f["source_id"]) if f["source_type"] == "document" else src_dates.get((f["source_type"], f["source_id"]))
        # a task/calendar "date" is a due/start date, not when the file learned it; use it only if in the past
        known = sd if f["source_type"] in ("document", "note", "communication", "expense") else (f.get("date") or sd)
        f["known_at"] = (known or "")[:10] or None
        if as_of and f["known_at"] and f["known_at"] > as_of:
            continue
        out.append(f)
    return out


def documents(as_of: str | None = None) -> list[dict]:
    docs = db.query("SELECT id, name, folder, doc_type, page_count, received_at FROM documents")
    return [d for d in docs if not as_of or not d["received_at"] or d["received_at"][:10] <= as_of]


def issue_key(*parts) -> str:
    return "xi_" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def today() -> str:
    return date.today().isoformat()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())
