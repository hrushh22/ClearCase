import { useEffect, useMemo, useState } from "react";
import dagre from "@dagrejs/dagre";
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import FullNetwork from "./FullNetwork";
import { useSource } from "../SourceViewer";
import { fmtDate } from "../../lib/api";
import { STATE } from "./EvidenceCoverage";

const ISSUE: Record<string, { glyph: string; label: string; cls: string }> = {
  contradiction: { glyph: "≠", label: "Contradiction", cls: "border-red-300 bg-red-50 text-red-900" },
  amount_mismatch: { glyph: "$≠", label: "Amount mismatch", cls: "border-red-300 bg-red-50 text-red-900" },
  missing_evidence: { glyph: "?", label: "Evidence gap", cls: "border-amber-300 bg-amber-50 text-amber-900 border-dashed" },
  timeline_gap: { glyph: "⏱", label: "Timeline", cls: "border-amber-300 bg-amber-50 text-amber-900 border-dashed" },
  dependency: { glyph: "⧗", label: "Waiting on", cls: "border-sky-300 bg-sky-50 text-sky-900" },
};
const ENTITY: Record<string, { glyph: string; cls: string }> = {
  injury: { glyph: "✚", cls: "border-red-200 bg-white text-red-900" },
  provider: { glyph: "⚕", cls: "border-emerald-200 bg-white text-emerald-900" },
  party: { glyph: "⚖", cls: "border-violet-200 bg-white text-violet-900" },
};
const SRC_LABEL: Record<string, string> = { note: "Note", communication: "Email/Call", task: "Task", calendar: "Calendar", document: "Document",
  custom_field: "Clio field", expense: "Clio charge", matter: "Matter", contact: "Contact" };
const EDGE: Record<string, { color: string; dash?: string; label: string }> = {
  INVOLVES: { color: "#94a3b8", label: "" },
  CONTRADICTS: { color: "#dc2626", dash: "6 3", label: "conflicts" },
  MISSING_EVIDENCE_FOR: { color: "#d97706", dash: "3 4", label: "missing" },
  DEPENDS_ON: { color: "#0284c7", dash: "3 4", label: "waiting on" },
  SUPPORTS: { color: "#059669", label: "supports" },
  EVIDENCE: { color: "#64748b", label: "evidence" },
  AFFECTS: { color: "#d97706", dash: "3 4", label: "affects" },
};

const SIZE: Record<string, [number, number]> = { claim: [270, 96], issue: [240, 64], entity: [210, 44], fact: [310, 86], center: [300, 96], action: [300, 70], header: [200, 24] };

// ------------------------------------------------------------------ node cards

function Card({ data }: NodeProps) {
  const d = data as any;
  const h = (
    <>
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
    </>
  );
  const [w, ht] = SIZE[d.card] || SIZE.entity;
  const style = { width: w, minHeight: ht };
  if (d.card === "header")
    return <div style={{ width: w }} className="text-[11px] font-semibold uppercase tracking-[0.15em] text-slate-400">{d.label}</div>;
  if (d.card === "claim" || d.card === "center") {
    const s = STATE[d.state] || STATE.limited;
    return (
      <div style={style} className={`cursor-pointer rounded-xl border bg-white px-3 py-2 shadow-sm transition hover:shadow-md ${d.card === "center" ? "border-rose-400 ring-4 ring-rose-100" : "border-slate-200"}`}>
        {h}
        <div className="flex items-start gap-2">
          <span aria-hidden className="text-rose-500">◆</span>
          <div className="line-clamp-2 flex-1 text-[13px] font-semibold leading-snug text-slate-900">{d.label}</div>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1 text-[11px]">
          <span className={`chip ${s.cls}`}><span aria-hidden>{s.glyph}</span>{d.state_label}</span>
          {d.verified != null && <span className="text-slate-500">{d.verified} verified</span>}
          {d.contradictions > 0 && <span className="text-red-700">· ≠ {d.contradictions}</span>}
          {d.gaps > 0 && <span className="text-amber-700">· ? {d.gaps}</span>}
        </div>
        {d.chips?.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {d.chips.map((c: any) => (
              <span key={c.id} className={`max-w-[120px] truncate rounded-full border px-1.5 text-[10px] ${(ENTITY[c.kind] || ENTITY.provider).cls}`} title={c.label}>
                {(ENTITY[c.kind] || ENTITY.provider).glyph} {c.label.replace(/\s*\(.*\)$/, "")}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
  if (d.card === "issue") {
    const t = ISSUE[d.issue_type] || ISSUE.missing_evidence;
    return (
      <div style={style} className={`cursor-pointer rounded-xl border px-3 py-2 shadow-sm transition hover:shadow-md ${t.cls} ${d.center ? "ring-4 ring-amber-100" : ""}`}>
        {h}
        <div className="text-[10px] font-semibold uppercase tracking-wide opacity-80"><span aria-hidden>{t.glyph}</span> {t.label}{d.verify_status === "needs_review" ? " · △ needs review" : ""}</div>
        <div className="line-clamp-2 text-[12px] font-medium leading-snug">{d.label}</div>
      </div>
    );
  }
  if (d.card === "fact") {
    return (
      <div style={style} className="cursor-pointer rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm transition hover:border-rose-300 hover:shadow-md" title="Open source">
        {h}
        <div className="line-clamp-3 text-[12px] leading-snug text-slate-800">{d.label}</div>
        <div className="mt-1 flex items-center gap-1 text-[10px] text-slate-500">
          <span className="rounded bg-rose-50 px-1.5 py-0.5 font-medium text-rose-700">↗ {SRC_LABEL[d.source_type] || d.source_type}{d.page ? ` p.${d.page}` : ""}</span>
          {d.date && <span>{fmtDate(d.date)}</span>}
        </div>
      </div>
    );
  }
  if (d.card === "action") {
    return (
      <div style={style} className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-900">
        {h}
        <div className="text-[10px] font-semibold uppercase tracking-wide">Suggested follow-up</div>
        <div className="line-clamp-2">{d.label}</div>
      </div>
    );
  }
  const e = ENTITY[d.kind] || ENTITY.provider;
  return (
    <div style={style} className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-[12px] shadow-sm ${e.cls}`} title={d.detail || d.label}>
      {h}
      <span aria-hidden>{e.glyph}</span><span className="line-clamp-1">{d.label}</span>
    </div>
  );
}
const nodeTypes = { card: Card };

function mkEdge(id: string, source: string, target: string, rel: string, count?: number | null, showLabel = true): Edge {
  const s = EDGE[rel] || EDGE.INVOLVES;
  const label = showLabel && !["SUPPORTS", "EVIDENCE", "INVOLVES"].includes(rel) ? s.label : count && count > 1 ? `${count} facts` : "";
  return {
    id, source, target, type: "smoothstep", label: label || undefined,
    labelStyle: { fontSize: 10, fill: s.color }, labelBgStyle: { fill: "#f8fafc" },
    style: { stroke: s.color, strokeDasharray: s.dash, strokeWidth: rel === "INVOLVES" ? 1 + Math.min(count || 1, 6) * 0.35 : 1.6 },
    markerEnd: { type: MarkerType.ArrowClosed, color: s.color, width: 12, height: 12 },
  };
}

// ---------------------------------------------------------------- layouts

/** Overview: propositions in a grid (those with issues nearest the issue columns), issues in two columns beside them,
 *  each placed level with what it affects. Injuries/people are chips inside the proposition cards, not separate nodes. */
function overviewLayout(ov: any): { nodes: Node[]; edges: Edge[] } {
  const byId: Record<string, any> = Object.fromEntries(ov.nodes.map((n: any) => [n.id, n]));
  const claims = ov.nodes.filter((n: any) => n.kind === "claim");
  const issues = ov.nodes.filter((n: any) => n.kind === "issue");
  const toClaims = ov.edges.filter((e: any) => e.relationship !== "INVOLVES" && byId[e.target]?.kind === "claim");
  const involves: Record<string, any[]> = {};
  ov.edges.filter((e: any) => e.relationship === "INVOLVES").forEach((e: any) => (involves[e.source] ||= []).push({ ...byId[e.target], count: e.count }));
  const waitingOn: Record<string, string> = {};
  ov.edges.filter((e: any) => e.relationship === "DEPENDS_ON").forEach((e: any) => (waitingOn[e.source] = byId[e.target]?.label));

  const [CW, CH] = SIZE.claim, [IW, IH] = SIZE.issue;
  const ROWS = Math.ceil(claims.length / 3), GX = 34, GY = 26;
  const issueCount = (id: string) => toClaims.filter((e: any) => e.target === id).length;
  const ordered = [...claims].sort((a: any, b: any) => issueCount(b.id) - issueCount(a.id));
  const left = IW * 2 + 40 + 120;  // two issue columns + gutter
  const nodes: Node[] = [];
  const claimY: Record<string, number> = {};
  ordered.forEach((n: any, k: number) => {
    const col = Math.floor(k / ROWS), row = k % ROWS;
    const pos = { x: left + col * (CW + GX), y: row * (CH + 22 + GY) };
    claimY[n.id] = pos.y;
    nodes.push({ id: n.id, type: "card", position: pos, data: { ...n, card: "claim", chips: (involves[n.id] || []).slice(0, 3) } });
  });
  // issues: linked ones in the inner column next to their proposition, the rest (e.g. waiting on a provider) in the outer column
  const target = (i: any) => toClaims.filter((e: any) => e.source === i.id).map((e: any) => claimY[e.target]);
  const linked = issues.filter((i: any) => target(i).length).sort((a: any, b: any) => Math.min(...target(a)) - Math.min(...target(b)));
  const other = issues.filter((i: any) => !target(i).length);
  const place = (list: any[], x: number, spread: boolean) => {
    let y = -Infinity;
    list.forEach((i: any) => {
      const want = spread ? Math.min(...target(i)) : y + IH + 16;
      y = Math.max(want, y + IH + 16, spread ? -Infinity : 0);
      nodes.push({ id: i.id, type: "card", position: { x, y: Number.isFinite(y) ? y : 0 },
        data: { ...i, card: "issue", label: waitingOn[i.id] && !i.label.includes(waitingOn[i.id]) ? `${i.label} · ${waitingOn[i.id]}` : i.label } });
    });
  };
  place(linked, IW + 40, true);
  place(other, 0, false);
  const top = -40;
  nodes.push({ id: "h_o", type: "card", position: { x: 0, y: top }, data: { card: "header", label: "Other open items" }, selectable: false, draggable: false });
  nodes.push({ id: "h_i", type: "card", position: { x: IW + 40, y: top }, data: { card: "header", label: "Issues to review" }, selectable: false, draggable: false });
  nodes.push({ id: "h_c", type: "card", position: { x: left, y: top }, data: { card: "header", label: "Key propositions" }, selectable: false, draggable: false });
  const edges = toClaims.map((e: any) => mkEdge(e.id, e.source, e.target, e.relationship, null, false));
  return { nodes, edges };
}

function column(items: any[], x: number, kind: string, gap = 18) {
  const [, h] = SIZE[kind];
  const total = items.length * (h + gap) - gap;
  return items.map((it, k) => ({ ...it, position: { x, y: k * (h + gap) - total / 2 } }));
}

function focusLayout(target: { kind: "claim" | "issue"; id: string }, x: any): { nodes: Node[]; edges: Edge[]; title: string } {
  const issuesById: Record<string, any> = Object.fromEntries(x.issues.map((i: any) => [i.id, i]));
  const nodes: Node[] = [], edges: Edge[] = [];
  const add = (id: string, data: any, position: any) => nodes.push({ id, type: "card", position, data });
  if (target.kind === "claim") {
    const p = x.propositions.find((p: any) => p.id === target.id);
    if (!p) return { nodes, edges, title: "" };
    add("center", { card: "center", label: p.title, state: p.state, state_label: p.state_label, verified: p.components.verified_sources,
      contradictions: p.contradictions.length, gaps: p.gaps.length }, { x: 420, y: -48 });
    const facts = column(p.evidence.slice(0, 7).map((e: any, k: number) => ({ id: `f${k}`, e })), 0, "fact");
    facts.forEach((f: any) => { add(f.id, { card: "fact", label: f.e.text || f.e.quote, ...f.e, ref: f.e }, f.position); edges.push(mkEdge(`ef${f.id}`, f.id, "center", "SUPPORTS")); });
    const right = column([...p.contradictions, ...p.gaps].map((iid: string) => issuesById[iid]).filter(Boolean).slice(0, 7).map((i: any) => ({ id: `issue_${i.id}`, i })), 860, "issue", 22);
    right.forEach((r: any) => {
      add(r.id, { card: "issue", label: r.i.title, issue_type: r.i.issue_type, issue_id: r.i.id, verify_status: r.i.verify_status }, r.position);
      edges.push({ ...mkEdge(`er${r.id}`, "center", r.id, r.i.issue_type.includes("contradiction") || r.i.issue_type === "amount_mismatch" ? "CONTRADICTS" : "MISSING_EVIDENCE_FOR"), markerStart: undefined });
    });
    if (!right.length) add("none", { card: "action", label: "No contradiction or evidence gap touches this proposition." }, { x: 860, y: -35 });
    return { nodes, edges, title: p.title };
  }
  const i = issuesById[target.id];
  if (!i) return { nodes, edges, title: "" };
  add("center", { card: "issue", center: true, label: i.title, issue_type: i.issue_type, verify_status: i.verify_status }, { x: 420, y: -32 });
  const ev = column(i.evidence_for.slice(0, 7).map((e: any, k: number) => ({ id: `f${k}`, e })), 0, "fact");
  ev.forEach((f: any) => { add(f.id, { card: "fact", label: f.e.text || f.e.quote, ...f.e, ref: f.e }, f.position); edges.push(mkEdge(`ef${f.id}`, f.id, "center", "EVIDENCE")); });
  const affected = x.propositions.filter((p: any) => p.contradictions.includes(i.id) || p.gaps.includes(i.id)).slice(0, 4);
  const right = column([...affected.map((p: any) => ({ id: p.id, p })), { id: "action", a: i.suggested_action }], 860, "claim", 24);
  right.forEach((r: any) => {
    if (r.a) { add("action", { card: "action", label: r.a }, r.position); edges.push(mkEdge("ea", "center", "action", "EVIDENCE")); return; }
    add(r.id, { card: "claim", label: r.p.title, state: r.p.state, state_label: r.p.state_label, verified: r.p.components.verified_sources,
      contradictions: r.p.contradictions.length, gaps: r.p.gaps.length }, r.position);
    edges.push(mkEdge(`ep${r.id}`, "center", r.id, "AFFECTS"));
  });
  return { nodes, edges, title: i.title };
}

// --------------------------------------------------------------------- view

type View = { mode: "overview" } | { mode: "focus"; kind: "claim" | "issue"; id: string } | { mode: "full" };

function Inner({ x, focus, onFocusIssue }: { x: any; focus: string[] | null; onFocusIssue?: (id: string) => void }) {
  const [view, setView] = useState<View>({ mode: "overview" });
  const flow = useReactFlow();
  const open = useSource();

  useEffect(() => {  // focus requests from the coverage list, issue list and spotlight
    const f = focus?.[0];
    if (!f) return;
    if (f.startsWith("p_")) setView({ mode: "focus", kind: "claim", id: f });
    else if (f.startsWith("issue_")) setView({ mode: "focus", kind: "issue", id: f.slice(6) });
  }, [focus]);

  const built = useMemo(() => view.mode === "overview" ? { ...overviewLayout(x.graph.overview), title: "" }
    : view.mode === "focus" ? focusLayout(view, x) : null, [view, x]);
  useEffect(() => { setTimeout(() => flow.fitView({ duration: 350, padding: 0.12 }), 30); }, [built]);

  const onNodeClick = (_: any, n: Node) => {
    const d = n.data as any;
    if (d.card === "fact" && d.ref?.source_type) return open(d.ref);
    if (d.card === "claim") return setView({ mode: "focus", kind: "claim", id: n.id });
    if (d.card === "issue" && d.issue_id) return setView({ mode: "focus", kind: "issue", id: d.issue_id });
  };

  return (
    <div className="overflow-hidden rounded-2xl border border-rose-100 bg-gradient-to-br from-rose-50/40 to-white">
      <div className="flex flex-wrap items-center gap-2 border-b bg-white px-3 py-2 text-sm">
        <nav className="flex min-w-0 flex-1 items-center gap-1" aria-label="Breadcrumb">
          <button className={`font-medium ${view.mode === "overview" ? "text-slate-900" : "text-rose-700 hover:underline"}`} onClick={() => setView({ mode: "overview" })}>Overview</button>
          {view.mode === "focus" && <><span className="text-slate-400">›</span><span className="truncate font-medium text-slate-900">{built?.title}</span></>}
          {view.mode === "full" && <><span className="text-slate-400">›</span><span className="font-medium">Full network</span></>}
        </nav>
        {view.mode === "focus" && view.kind === "issue" && onFocusIssue && (
          <button className="btn-ghost border" onClick={() => onFocusIssue(view.id)}>Open in issue list</button>
        )}
        <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs">
          <button onClick={() => setView({ mode: "overview" })} className={`rounded-md px-2.5 py-1 ${view.mode !== "full" ? "bg-white font-medium shadow-sm" : "text-slate-600"}`}>Overview</button>
          <button onClick={() => setView({ mode: "full" })} className={`rounded-md px-2.5 py-1 ${view.mode === "full" ? "bg-white font-medium shadow-sm" : "text-slate-600"}`}>Full network</button>
        </div>
      </div>
      {view.mode === "full" ? (
        <div className="p-2"><FullNetwork graph={x.graph} focus={focus} onFocusIssue={onFocusIssue} /></div>
      ) : (
        <>
          <div className="h-[460px] sm:h-[560px] 2xl:h-[680px]">
            <ReactFlow nodes={built!.nodes} edges={built!.edges} nodeTypes={nodeTypes} onNodeClick={onNodeClick} fitView minZoom={0.2} maxZoom={1.6}
              nodesConnectable={false} proOptions={{ hideAttribution: true }}>
              <Background gap={28} color="#e2e8f0" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t bg-white px-3 py-2 text-[11px] text-slate-600">
            {view.mode === "overview" ? (
              <>
                <span><b>Click</b> a proposition or issue to see the evidence behind it.</span>
                <Legend color="#dc2626" dash="6 3" label="conflicts with" />
                <Legend color="#d97706" dash="3 4" label="missing evidence for" />
                <Legend color="#0284c7" dash="3 4" label="waiting on" />
                <span>Chips inside a card = injuries and people it involves.</span>
              </>
            ) : (
              <>
                <span><b>Click</b> an evidence card to open the source at the cited page.</span>
                <Legend color="#059669" label="supports" />
                <Legend color="#dc2626" dash="6 3" label="conflicts" />
                <Legend color="#d97706" dash="3 4" label="missing / affects" />
              </>
            )}
            <span className="ml-auto">✓✓ well corroborated · ✓ supported · ◌ limited · ? incomplete · ≠ conflicting · △ needs review</span>
          </div>
        </>
      )}
    </div>
  );
}

function Legend({ color, dash, label }: { color: string; dash?: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <svg width="26" height="6" aria-hidden><line x1="0" y1="3" x2="26" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dash} /></svg>{label}
    </span>
  );
}

export default function CaseConstellation(props: { x: any; focus: string[] | null; onFocusIssue?: (id: string) => void }) {
  return <ReactFlowProvider><Inner {...props} /></ReactFlowProvider>;
}
