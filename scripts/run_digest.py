"""Print a short text summary of the cached digest (no LLM calls, no Clio calls)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.digest import load_digest  # noqa: E402


def main() -> None:
    d = load_digest()
    if not d:
        print("No digest yet. Run scripts/sync.py first.")
        return
    s, k = d["snapshot"], d["kpis"]
    print(f"{s['client']['name']} | {s['title']} | Clio stage {s['clio_stage']} | digest {d['content_hash'][:10]} @ {d['created_at']}")
    print(f"Case value: {k['case_value']['value']} ({k['case_value']['basis']})")
    print(f"Coverage:   {k['coverage']['headline']} ({k['coverage']['basis']})")
    print(f"Specials:   {k['specials']['value']}  provider sum {k['specials']['provider_sum']}")
    print(f"Firm spend: {k['firm_spend']['value']}")
    print(f"Stage:      {d['stage']['stage']} via {d['stage']['method']}; last movement {d['stage']['last_movement_at']}")
    print(f"Facts:      {d['fact_stats']}  extractors {d['extractors']}")
    print("Top 10:")
    for t in d["top10"]["items"]:
        print(f"  {t['score']:3d} {t['date']} {t['title'][:70]} :: {t['why_it_matters']}")
    a = d["attention"]
    print(f"Attention: {len(a['overdue'])} overdue, {len(a['upcoming'])} upcoming, {len(a['waiting'])} waiting")
    c = d["contact"]
    print(f"Last client contact: {c['last'] and c['last']['date']} ({c['days_since']} days ago)")
    print("Liens:", [(l["name"], l["amount"]) for l in d["waterfall"]["liens"]])


if __name__ == "__main__":
    main()
