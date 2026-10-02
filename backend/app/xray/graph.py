"""CASE CONSTELLATION: facts/entities -> nodes and typed edges, all derived from existing data.

Edges are deterministic (from fact sources, entity mentions, region words, issue references) except
CONTRADICTS edges from LLM-paired contradictions, which carry method="llm" and are drawn as inferred.
"""
from __future__ import annotations

from ..agents.share_policy import mentions, provider_contacts
from .common import REGION_LABEL, regions_in

SOURCE_LABEL = {"note": "Note", "communication": "Email/Call", "task": "Task", "calendar": "Calendar", "document": "Document",
                "custom_field": "Clio field", "expense": "Clio charge", "matter": "Matter", "contact": "Contact"}


def build(facts: list[dict], props: list[dict], issues: list[dict], injury: dict, bundle: dict, docs: list[dict],
          new_fact_ids: set[str], titles: dict) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    by_id = {f["fact_id"]: f for f in facts}

    def node(nid, ntype, label, **kw):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "label": label[:80], **kw}
        return nid

    def edge(a, b, rel, method="rule", status="verified", fact_ids=None):
        if a in nodes and b in nodes and a != b:
            edges.append({"id": f"e{len(edges)}", "source": a, "target": b, "relationship": rel, "method": method,
                          "verify_status": status, "source_fact_ids": fact_ids or []})

    m = bundle.get("matter", {})
    client = next((c for c in bundle.get("contacts", []) if c.get("is_client")), None)
    if client:
        node("client", "person", client["name"], ref={"source_type": "contact", "source_id": client["id"]})
    providers = provider_contacts(bundle)
    prov_ids = {p["id"] for p in providers}
    for p in providers:
        node(f"prov_{p['id']}", "provider", p["name"], detail=p["relationship"], tokens=p["tokens"])
    for c in bundle.get("contacts", []):
        if c["id"] in prov_ids or c.get("is_client") or not c.get("relationship"):
            continue
        if c.get("type") == "Person" and c.get("company") in {p["name"] for p in providers}:
            continue
        node(f"party_{c['id']}", "party", c["name"], detail=c["relationship"], tokens=[c["name"].split()[-1].lower()])

    for r in injury["regions"]:
        node(f"inj_{r['key']}", "injury", REGION_LABEL[r["key"]] + (f" ({'/'.join(r['sides'])})" if r["sides"] else ""),
             state=r["state"], region=r["key"])
        if client:
            edge("client", f"inj_{r['key']}", "RELATED_TO")

    # propositions ("claims") and the facts behind them
    chosen: set[str] = set()
    for p in props:
        node(p["id"], "claim", p["title"], state=p["state"], state_label=p["state_label"])
        for fid in p["fact_ids"][:5]:
            chosen.add(fid)
        if p["category"] == "injury":
            edge(p["id"], f"inj_{p['id'][len('p_injury_'):]}", "RELATED_TO")
    for i in issues:
        for fid in i.get("related_fact_ids", [])[:4]:
            chosen.add(fid)

    for fid in sorted(chosen):
        f = by_id.get(fid)
        if not f:
            continue
        status = "supported" if f["verify_status"] == "supported" else "needs_review"
        node(f"fact_{fid}", "fact", f["text"], fact_type=f["type"], status=status, new=fid in new_fact_ids,
             ref={"fact_id": fid, "source_type": f["source_type"], "source_id": f["source_id"], "page": f.get("page"), "quote": f["quote"]},
             date=f.get("date") or f.get("known_at"))
        sid = f"src_{f['source_type']}_{f['source_id']}"
        title = titles.get((f["source_type"], f["source_id"])) or SOURCE_LABEL.get(f["source_type"], f["source_type"])
        node(sid, "document" if f["source_type"] == "document" else "source", title,
             source_kind=SOURCE_LABEL.get(f["source_type"], f["source_type"]),
             ref={"source_type": f["source_type"], "source_id": f["source_id"], "page": f.get("page"), "quote": f["quote"]})
        edge(sid, f"fact_{fid}", "EVIDENCE_FOR", fact_ids=[fid])
        hay = f["text"] + " " + (f.get("entity") or "")
        for n in list(nodes.values()):
            if n["type"] in ("provider", "party") and n.get("tokens") and mentions(hay, n["tokens"]):
                edge(f"fact_{fid}", n["id"], "BILLED_BY" if f["type"] == "bill" and n["type"] == "provider" else "MENTIONS", fact_ids=[fid])
        for key, _ in regions_in(hay):
            if f["type"] in ("injury", "treatment") and f"inj_{key}" in nodes:
                edge(f"fact_{fid}", f"inj_{key}", "EVIDENCE_FOR", fact_ids=[fid])
    for p in props:
        for fid in p["fact_ids"][:5]:
            edge(f"fact_{fid}", p["id"], "SUPPORTS", status="verified" if by_id.get(fid, {}).get("verify_status") == "supported" else "needs_review",
                 fact_ids=[fid])

    # treated-by: region <- provider when a treatment fact names both
    for f in facts:
        if f["type"] != "treatment":
            continue
        hay = f["text"] + " " + (f.get("entity") or "")
        for p in providers:
            if mentions(hay, p["tokens"]):
                for key, _ in regions_in(hay):
                    if f"inj_{key}" in nodes and not any(e["source"] == f"inj_{key}" and e["target"] == f"prov_{p['id']}" for e in edges):
                        edge(f"inj_{key}", f"prov_{p['id']}", "TREATED_BY", fact_ids=[f["fact_id"]])

    # issues: contradictions between facts, gaps against claims/providers
    for i in issues:
        ids = [x for x in i.get("related_fact_ids", []) if f"fact_{x}" in nodes]
        status = "verified" if i.get("verify_status") == "verified" else "needs_review"
        if i["issue_type"] in ("contradiction", "amount_mismatch") and len(ids) >= 2:
            edge(f"fact_{ids[0]}", f"fact_{ids[1]}", "CONTRADICTS", method=i.get("method", "rule"), status=status, fact_ids=ids[:2])
        else:
            iid = node(f"issue_{i['id']}", "gap" if i["issue_type"] != "contradiction" else "issue", i["title"], issue_id=i["id"],
                       issue_type=i["issue_type"], severity=i["severity"])
            for x in ids[:3]:
                edge(f"fact_{x}", iid, "RELATED_TO", fact_ids=[x])
            target = next((p["id"] for p in props if i["id"] in p["gaps"] or i["id"] in p["contradictions"]), None)
            if target:
                edge(iid, target, "MISSING_EVIDENCE_FOR" if i["issue_type"] != "contradiction" else "CONTRADICTS", status=status)
            if i.get("entity"):
                for p in providers:
                    if mentions(i["entity"], p["tokens"]):
                        edge(iid, f"prov_{p['id']}", "DEPENDS_ON" if i["issue_type"] == "dependency" else "MISSING_EVIDENCE_FOR", status=status)

    ov = overview(nodes, edges, props, issues)
    used = {e["source"] for e in edges} | {e["target"] for e in edges}
    out_nodes = [n for n in nodes.values() if n["id"] in used or n["type"] in ("claim", "person")]
    for n in out_nodes:
        n.pop("tokens", None)
    return {"nodes": out_nodes, "edges": edges, "overview": ov,
            "legend": {"node_types": sorted({n["type"] for n in out_nodes}), "relationships": sorted({e["relationship"] for e in edges})}}


def overview(nodes: dict, edges: list[dict], props: list[dict], issues: list[dict], max_links: int = 3) -> dict:
    """Readable summary graph: propositions, issues and the people/injuries they involve.

    Facts and sources are folded into their proposition (shown as counts); fact-level links become one
    weighted link per proposition/entity pair, keeping each proposition's strongest few.
    """
    ov_nodes, ov_edges = [], []
    supports: dict[str, set[str]] = {}
    for e in edges:
        if e["relationship"] == "SUPPORTS":
            supports.setdefault(e["target"], set()).add(e["source"])
    fact_links: dict[str, dict[str, int]] = {}
    for e in edges:
        if e["source"].startswith("fact_") and e["relationship"] in ("MENTIONS", "BILLED_BY", "EVIDENCE_FOR") and                 nodes.get(e["target"], {}).get("type") in ("provider", "party", "injury"):
            fact_links.setdefault(e["source"], {}).setdefault(e["target"], 0)
            fact_links[e["source"]][e["target"]] += 1
    for p in props:
        ov_nodes.append({"id": p["id"], "kind": "claim", "label": p["title"], "state": p["state"], "state_label": p["state_label"],
                         "verified": p["components"]["verified_sources"], "contradictions": len(p["contradictions"]), "gaps": len(p["gaps"])})
        counts: dict[str, int] = {}
        for fid in supports.get(p["id"], set()) | {f"fact_{x}" for x in p["fact_ids"]}:
            for ent, n in fact_links.get(fid, {}).items():
                counts[ent] = counts.get(ent, 0) + n
        if p["category"] == "injury":
            counts[f"inj_{p['id'][len('p_injury_'):]}"] = counts.get(f"inj_{p['id'][len('p_injury_'):]}", 0) + 1000  # always keep its region
        for ent, n in sorted(counts.items(), key=lambda kv: -kv[1])[:max_links]:
            if ent in nodes:
                ov_edges.append({"id": f"o{len(ov_edges)}", "source": p["id"], "target": ent, "relationship": "INVOLVES", "count": n % 1000 or None})
    for i in issues:
        targets = [p["id"] for p in props if i["id"] in p["contradictions"] or i["id"] in p["gaps"]]
        ov_nodes.append({"id": f"issue_{i['id']}", "kind": "issue", "issue_id": i["id"], "issue_type": i["issue_type"], "label": i["title"],
                         "severity": i["severity"], "verify_status": i.get("verify_status")})
        rel = "CONTRADICTS" if i["issue_type"] in ("contradiction", "amount_mismatch") else "MISSING_EVIDENCE_FOR"
        for t in targets[:2]:
            ov_edges.append({"id": f"o{len(ov_edges)}", "source": f"issue_{i['id']}", "target": t, "relationship": rel})
        if not targets and i.get("entity"):
            ent = next((n["id"] for n in nodes.values() if n["type"] in ("provider", "party") and n["label"] == i["entity"]), None)
            if ent:
                ov_edges.append({"id": f"o{len(ov_edges)}", "source": f"issue_{i['id']}", "target": ent, "relationship": "DEPENDS_ON"})
    linked = {e["target"] for e in ov_edges} | {e["source"] for e in ov_edges}
    for n in nodes.values():
        if n["type"] in ("provider", "party", "injury") and n["id"] in linked:
            ov_nodes.append({"id": n["id"], "kind": n["type"], "label": n["label"], "detail": n.get("detail"), "state": n.get("state")})
    return {"nodes": ov_nodes, "edges": ov_edges}
