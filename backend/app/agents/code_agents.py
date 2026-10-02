"""Deterministic agents (no LLM): attention, last client contact, change detector, client photo."""
from __future__ import annotations

import base64
import re
from collections import Counter
from datetime import date, timedelta

WAITING_RX = r"^By (medical provider|client|defen|opposing)|awaiting|waiting|no (date|response|reply)|chaser|(second|third) request|has not|have not sent|sent nothing"


def _ref(s: dict) -> dict:
    return {"source_type": s["source_type"], "source_id": s["source_id"], "title": s["title"], "date": s.get("date")}


def attention(sources: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    t = today.isoformat()
    week = (today + timedelta(days=7)).isoformat()
    fortnight = (today + timedelta(days=14)).isoformat()
    overdue, upcoming, waiting = [], [], []
    for s in sources:
        m = s["meta"]
        if s["source_type"] == "task" and (m.get("status") or "").lower() not in ("complete", "completed", "done"):
            due = (m.get("due_at") or "")[:10]
            item = {**_ref(s), "due": due, "assignee": m.get("assignee"), "kind": "task",
                    "detail": s["text"].split("\n\n", 1)[-1][:220]}
            is_waiting = bool(re.search(WAITING_RX, s["title"] + " " + s["text"], re.I))
            if is_waiting:
                who = re.match(r"By [^:]+:\s*(.+?)\s+-\s+", s["title"] or "")
                item["waiting_on"] = who.group(1) if who else None
                waiting.append(item)
            if due and due < t:
                overdue.append({**item, "days_overdue": (today - date.fromisoformat(due)).days})
            elif due and due <= week:
                upcoming.append(item)
        elif s["source_type"] == "calendar":
            start = (m.get("start_at") or "")[:10]
            if t <= start <= fortnight:
                upcoming.append({**_ref(s), "due": start, "kind": "calendar", "detail": s["text"].split("\n\n", 1)[-1][:220]})
    key = lambda x: x.get("due") or ""
    return {"today": t, "overdue": sorted(overdue, key=key), "upcoming": sorted(upcoming, key=key),
            "waiting": sorted(waiting, key=key)}


def client_contact(sources: list[dict], client_id: str | None, client_name: str | None) -> dict:
    """Last real two-way contact with the client (email/phone where the client is a party)."""
    rows = []
    for s in sources:
        if s["source_type"] != "communication":
            continue
        people = (s["meta"].get("senders") or []) + (s["meta"].get("receivers") or [])
        ids = {str(p.get("id")) for p in people}
        names = {(p.get("name") or "").lower() for p in people}
        if (client_id and client_id in ids) or (client_name and client_name.lower() in names):
            inbound = any(str(p.get("id")) == client_id for p in s["meta"].get("senders") or [])
            rows.append({**_ref(s), "channel": "phone" if "Phone" in (s["meta"].get("type") or "") else "email",
                         "direction": "from client" if inbound else "to client"})
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    months = Counter((r["date"] or "")[:7] for r in rows if r.get("date"))
    all_months = Counter((s.get("date") or "")[:7] for s in sources if s["source_type"] == "communication" and s.get("date"))
    last = rows[0] if rows else None
    last_inbound = next((r for r in rows if r["direction"] == "from client"), None)
    days = (date.today() - date.fromisoformat(last["date"])).days if last and last.get("date") else None
    return {"last": last, "last_from_client": last_inbound, "days_since": days, "count": len(rows),
            "heatmap": [{"month": k, "client": months.get(k, 0), "all": v} for k, v in sorted(all_months.items())],
            "recent": rows[:6]}


def detect_changes(prev: dict | None, cur: dict) -> dict:
    """Diff two digests: new facts, changed KPIs, new overdue tasks, stage change."""
    if not prev:
        return {"first_view": True, "items": []}
    items = []
    if (prev.get("stage") or {}).get("stage") != (cur.get("stage") or {}).get("stage"):
        items.append({"kind": "stage", "summary": f"Stage moved from {prev['stage'].get('stage')} to {cur['stage'].get('stage')}",
                      "source": (cur["stage"].get("evidence") or [None])[0]})
    for k, label in [("case_value", "Estimated case value"), ("specials", "Medical specials"), ("firm_spend", "Firm spend")]:
        a, b = (prev.get("kpis") or {}).get(k, {}).get("value"), (cur.get("kpis") or {}).get(k, {}).get("value")
        if a != b:
            items.append({"kind": "kpi", "summary": f"{label} changed from {_fmt(a)} to {_fmt(b)}",
                          "source": ((cur["kpis"][k].get("sources") or [None])[0])})
    pc, cc = (prev.get("kpis") or {}).get("coverage", {}), (cur.get("kpis") or {}).get("coverage", {})
    if pc.get("headline") != cc.get("headline"):
        items.append({"kind": "kpi", "summary": f"Coverage now reads: {cc.get('headline')}", "source": (cc.get("sources") or [None])[0]})
    prev_over = {(o["source_type"], o["source_id"]) for o in (prev.get("attention") or {}).get("overdue", [])}
    for o in (cur.get("attention") or {}).get("overdue", []):
        if (o["source_type"], o["source_id"]) not in prev_over:
            items.append({"kind": "overdue", "summary": f"Newly overdue: {o['title']}", "source": o})
    prev_ids = set(prev.get("fact_ids") or [])
    new_facts = [f for f in cur.get("facts", []) if f["fact_id"] not in prev_ids]
    new_facts.sort(key=lambda f: f.get("date") or "", reverse=True)
    for f in new_facts[:15]:
        items.append({"kind": "new_fact", "summary": f["text"], "source": f})
    return {"first_view": False, "items": items, "new_fact_count": len(new_facts)}


def _fmt(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else str(v)


YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


def _face_model():
    from ..config import DATA_DIR

    path = DATA_DIR / "models" / "yunet.onnx"
    if not path.exists():
        import httpx

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            r = httpx.get(YUNET_URL, follow_redirects=True, timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
        except Exception:
            return None
    return path


def client_photo(documents: list[dict]) -> dict | None:
    """Find a face in intake documents (e.g. a scanned photo ID) and crop it. OpenCV YuNet, local.

    Only intake documents are scanned, so a provider's or expert's photo is never mistaken for the client.
    """
    try:
        import cv2
        import numpy as np
        import pymupdf
    except ImportError:
        return None
    model = _face_model()
    if not model:
        return None
    for d in sorted(documents, key=lambda d: d["name"]):
        if d["doc_type"] != "intake":
            continue
        try:
            doc = pymupdf.open(d["local_path"])
        except Exception:
            continue
        for page in list(doc)[:3]:
            if not page.get_images():
                continue
            pix = page.get_pixmap(dpi=200)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()
            bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            det = cv2.FaceDetectorYN.create(str(model), "", (bgr.shape[1], bgr.shape[0]), 0.7)
            _, faces = det.detect(bgr)
            if faces is not None and len(faces):
                x, y, w, h = [int(v) for v in max(faces, key=lambda f: f[2] * f[3])[:4]]
                pad = int(0.35 * w)
                crop = bgr[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
                ok, buf = cv2.imencode(".jpg", crop)
                if ok:
                    return {"data_url": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode(),
                            "source": {"source_type": "document", "source_id": d["id"], "page": page.number + 1,
                                       "title": d["name"], "quote": None}}
    return None
