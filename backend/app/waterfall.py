"""Settlement waterfall. Deterministic code, never an LLM.

client_net = gross - gross*fee_pct - sum(expenses) - sum(lien_i * (1 - reduction_i))

Liens are paid in `order` from what is left after fee and costs; each is marked fully /
partially / not covered for the chosen gross. Fee %, reductions and payment order are not in
the case data, so they are explicit, adjustable assumptions (defaults below).
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_FEE_PCT = 1 / 3


@dataclass
class Lien:
    name: str
    amount: float
    reduction: float = 0.0  # 0..1
    include: bool = True
    kind: str = "bill"


@dataclass
class WaterfallInput:
    gross: float
    fee_pct: float = DEFAULT_FEE_PCT
    expenses: list[float] = field(default_factory=list)
    liens: list[Lien] = field(default_factory=list)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute(inp: WaterfallInput) -> dict:
    if inp.gross < 0:
        raise ValueError("gross must be >= 0")
    fee_pct = _clamp(inp.fee_pct, 0.0, 1.0)
    gross = round(inp.gross, 2)
    fee = round(gross * fee_pct, 2)
    costs = round(sum(inp.expenses), 2)
    remaining = gross - fee - costs
    rows = []
    lien_total = 0.0
    for position, l in enumerate([l for l in inp.liens if l.include], start=1):
        red = _clamp(l.reduction, 0.0, 1.0)
        net = round(l.amount * (1 - red), 2)
        paid = round(_clamp(remaining, 0.0, net), 2)
        remaining -= net
        lien_total += net
        status = "full" if paid >= net - 0.005 else ("partial" if paid > 0 else "none")
        rows.append({"name": l.name, "kind": l.kind, "position": position, "billed": round(l.amount, 2), "reduction": red,
                     "net": net, "saved": round(l.amount - net, 2), "paid": paid, "status": status,
                     "covered_pct": round(paid / net, 4) if net else 1.0})
    client_net = round(gross - fee - costs - lien_total, 2)
    steps = [{"label": "Gross settlement", "value": gross, "kind": "gross"},
             {"label": f"Attorney fee ({fee_pct * 100:.1f}%)", "value": -fee, "kind": "fee"},
             {"label": "Case costs", "value": -costs, "kind": "costs"}]
    steps += [{"label": r["name"], "value": -r["net"], "kind": "lien", "status": r["status"]} for r in rows]
    steps.append({"label": "Client net", "value": client_net, "kind": "net"})
    return {"gross": gross, "fee_pct": fee_pct, "fee": fee, "costs": costs, "liens": rows, "lien_total": round(lien_total, 2),
            "client_net": client_net, "shortfall": client_net < 0, "steps": steps}


def breakeven_gross(fee_pct: float, costs: float, lien_total: float) -> float | None:
    """Smallest gross at which every included lien is fully paid (client_net >= 0)."""
    if fee_pct >= 1:
        return None
    return round((costs + lien_total) / (1 - fee_pct), 2)
