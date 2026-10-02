"""The firm's saved settlement scenario, and one provider's view of it (their own row only)."""
from __future__ import annotations

from . import db
from .agents.share_policy import mentions
from .waterfall import DEFAULT_FEE_PCT, Lien, WaterfallInput, compute


def ordered_liens(d: dict, settings: dict) -> list[Lien]:
    base = {l["name"]: l for l in d["waterfall"]["liens"]}
    order = [n for n in settings.get("order", []) if n in base] + [n for n in base if n not in settings.get("order", [])]
    per = settings.get("liens", {})
    return [Lien(name=n, amount=base[n]["amount"], kind=base[n]["kind"], reduction=float(per.get(n, {}).get("reduction", 0)),
                 include=bool(per.get(n, {}).get("include", True))) for n in order]


def provider_waterfall(d: dict, provider: dict) -> dict:
    """The firm's saved scenario, reduced to one provider's own row (other providers' amounts never leave)."""
    s = db.get_setting("waterfall", {}) or {}
    res = compute(WaterfallInput(gross=s.get("gross", d["waterfall"]["suggested_gross"]), fee_pct=s.get("fee_pct", DEFAULT_FEE_PCT),
                                 expenses=[e["amount"] for e in d["waterfall"]["expenses"]], liens=ordered_liens(d, s)))
    rows = res["liens"]
    for r in rows:
        r["mine"] = mentions(r["name"], provider["tokens"])
    return {"liens": [r for r in rows if r["mine"]], "count": len(rows)}


def waterfall_text(wf: dict) -> tuple[str, dict] | None:
    """The provider's place-in-line claim text, or None when their office has no line."""
    if not wf or not wf.get("liens"):
        return None
    r = wf["liens"][0]
    text = (f"Your office's balance of ${r['billed']:,.2f} is number {r['position']} of {wf['count']} in the payment line "
            f"under the firm's current working scenario.")
    return text, {"billed": r["billed"], "net": r["net"], "position": r["position"], "count": wf["count"], "status": r.get("status")}
