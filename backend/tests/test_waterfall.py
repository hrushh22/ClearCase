import pytest

from app.waterfall import Lien, WaterfallInput, breakeven_gross, compute


def test_formula_matches_plan():
    r = compute(WaterfallInput(gross=100_000, fee_pct=0.333, expenses=[1000, 410],
                               liens=[Lien("Medicaid", 22_180), Lien("Chiro", 17_400, reduction=0.25)]))
    expected = 100_000 - 100_000 * 0.333 - 1410 - 22_180 - 17_400 * 0.75
    assert r["client_net"] == pytest.approx(expected, abs=0.01)
    assert r["fee"] == 33_300
    assert r["costs"] == 1410
    assert r["liens"][1]["saved"] == pytest.approx(4350)


def test_coverage_status_full_partial_none():
    r = compute(WaterfallInput(gross=30_000, fee_pct=1 / 3, expenses=[0],
                               liens=[Lien("A", 15_000), Lien("B", 10_000), Lien("C", 5_000)]))
    # available after fee: 20,000 -> A full, B partial (5,000 of 10,000), C none
    assert [l["status"] for l in r["liens"]] == ["full", "partial", "none"]
    assert r["liens"][1]["paid"] == pytest.approx(5000, abs=0.01)
    assert r["shortfall"] is True


def test_excluded_liens_and_full_reduction():
    r = compute(WaterfallInput(gross=10_000, fee_pct=0, liens=[Lien("A", 5000, include=False), Lien("B", 5000, reduction=1.0)]))
    assert r["client_net"] == 10_000
    assert len(r["liens"]) == 1 and r["liens"][0]["net"] == 0 and r["liens"][0]["status"] == "full"


def test_inputs_are_clamped_and_validated():
    r = compute(WaterfallInput(gross=1000, fee_pct=1.5, liens=[Lien("A", 100, reduction=-1)]))
    assert r["fee"] == 1000 and r["liens"][0]["net"] == 100
    with pytest.raises(ValueError):
        compute(WaterfallInput(gross=-1))


def test_steps_sum_to_client_net():
    r = compute(WaterfallInput(gross=250_000, expenses=[1410], liens=[Lien("A", 22_180), Lien("B", 38_500, reduction=0.3)]))
    assert sum(s["value"] for s in r["steps"][:-1]) == pytest.approx(r["client_net"], abs=0.02)


def test_breakeven():
    assert breakeven_gross(0.5, 100, 900) == 2000
