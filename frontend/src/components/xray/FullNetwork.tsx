import { useEffect, useMemo, useState } from "react";
import {
  Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Cite, useSource } from "../SourceViewer";
import { fmtDate } from "../../lib/api";

// Node look: shape + glyph + color, so status is never encoded by color alone
const TYPE: Record<string, { label: string; glyph: string; cls: string; col: number }> = {
  document: { label: "Document", glyph: "▤", cls: "bg-slate-50 border-slate-300 text-slate-700", col: 0 },
  source: { label: "Note / email / record", glyph: "✉", cls: "bg-slate-50 border-slate-300 text-slate-700", col: 0 },
  fact: { label: "Fact", glyph: "•", cls: "bg-white border-slate-300 text-slate-800", col: 1 },
  claim: { label: "Proposition", glyph: "◆", cls: "bg-rose-50 border-rose-400 text-rose-900 font-semibold", col: 2 },
  issue: { label: "Contradiction", glyph: "≠", cls: "bg-red-50 border-red-400 text-red-900", col: 2 },
  gap: { label: "Gap / open item", glyph: "?", cls: "bg-amber-50 border-amber-400 border-dashed text-amber-900", col: 2 },
  injury: { label: "Injury region", glyph: "✚", cls: "bg-red-50 border-red-300 text-red-900", col: 3 },
  provider: { label: "Provider", glyph: "⚕", cls: "bg-emerald-50 border-emerald-400 text-emerald-900", col: 3 },
  party: { label: "Party", glyph: "⚖", cls: "bg-violet-50 border-violet-300 text-violet-900", col: 3 },
  person: { label: "Client", glyph: "☺", cls: "bg-rose-600 border-rose-700 text-white font-semibold", col: 3 },
};

const REL: Record<string, { color: string; dash?: string; label?: string }> = {
  SUPPORTS: { color: "#059669" },
  EVIDENCE_FOR: { color: "#94a3b8" },
  CONTRADICTS: { color: "#dc2626", dash: "6 3", label: "≠ contradicts" },
  MISSING_EVIDENCE_FOR: { color: "#d97706", dash: "2 4", label: "missing" },
  DEPENDS_ON: { color: "#d97706", dash: "2 4", label: "waiting on" },
  MENTIONS: { color: "#cbd5e1" },
  BILLED_BY: { color: "#0d9488", label: "billed by" },
  TREATED_BY: { color: "#0d9488", label: "treated by" },
  RELATED_TO: { color: "#cbd5e1" },
};

const STATUS_GLYPH: Record<string, string> = {
  supported: "✓", needs_review: "△", conflicting: "≠", well_corroborated: "✓✓", limited: "◌", incomplete: "?",
};

function XNode({ data }: NodeProps) {
  const d = data as any;
  const t = TYPE[d.type] || TYPE.fact;
  const status = d.state || d.status;
  return (
    <div className={`rounded-lg border px-2 py-1 text-[11px] leading-tight shadow-sm transition-opacity ${t.cls} ${d.dim ? "opacity-15" : ""}
      ${d.selected ? "ring-4 ring-rose-300" : ""} ${d.highlight ? "ring-2 ring-amber-400" : ""}`}
      style={{ width: d.type === "fact" ? 210 : 180 }} title={d.label}>
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !bg-slate-300" />
      <div className="flex items-start gap-1">
        <span aria-hidden className="shrink-0">{t.glyph}</span>
        <span className="line-clamp-2">{d.label}</span>
        {status && <span className="ml-auto shrink-0 font-bold" aria-label={status}>{STATUS_GLYPH[status] || ""}</span>}
        {d.new && <span className="ml-1 shrink-0 rounded bg-sky-600 px-1 text-[9px] text-white">NEW</span>}
      </div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !bg-slate-300" />
    </div>
  );
}

const nodeTypes = { x: XNode };

/** Columns by role (evidence -> facts -> propositions/issues -> people), wrapped so no column gets too tall. */
function layout(nodes: any[]) {
  const byCol: Record<number, any[]> = {};
  nodes.forEach((n) => (byCol[(TYPE[n.type] || TYPE.fact).col] ||= []).push(n));
  const pos: Record<string, { x: number; y: number }> = {};
  let x = 0;
  [0, 1, 2, 3].forEach((c) => {
    const list = (byCol[c] || []).sort((a, b) => (a.type + a.label).localeCompare(b.type + b.label));
    const per = 18;
    const sub = Math.max(1, Math.ceil(list.length / per));
    list.forEach((n, i) => { pos[n.id] = { x: x + Math.floor(i / per) * 235, y: (i % per) * 62 }; });
    x += sub * 235 + 140;
  });
  return pos;
}

function neighborhood(start: string, edges: any[], depth = 2) {
  const keep = new Set([start]);
  let frontier = [start];
  const rels = new Set(["SUPPORTS", "EVIDENCE_FOR", "CONTRADICTS", "MISSING_EVIDENCE_FOR", "DEPENDS_ON", "RELATED_TO", "TREATED_BY", "BILLED_BY"]);
  for (let d = 0; d < depth; d++) {
    const next: string[] = [];
    edges.forEach((e) => {
      if (!rels.has(e.relationship)) return;
      if (frontier.includes(e.source) && !keep.has(e.target)) { keep.add(e.target); next.push(e.target); }
      if (frontier.includes(e.target) && !keep.has(e.source)) { keep.add(e.source); next.push(e.source); }
    });
    frontier = next;
  }
  return keep;
}

function Inner({ graph, focus, onFocusIssue }: { graph: any; focus: string[] | null; onFocusIssue?: (id: string) => void }) {
  const [types, setTypes] = useState<Record<string, boolean>>(() => Object.fromEntries(Object.keys(TYPE).map((t) => [t, t !== "source"])));
  const [selected, setSelected] = useState<string | null>(null);
  const [edgeSel, setEdgeSel] = useState<any>(null);
  const [why, setWhy] = useState<Set<string> | null>(null);
  const [pos, setPos] = useState<Record<string, { x: number; y: number }>>({});
  const flow = useReactFlow();
  const open = useSource();

  const visibleNodes = useMemo(() => graph.nodes.filter((n: any) => types[n.type] ?? true), [graph, types]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((n: any) => n.id)), [visibleNodes]);
  const base = useMemo(() => layout(visibleNodes), [visibleNodes]);
  useEffect(() => { setPos({}); }, [graph]);

  useEffect(() => {
    if (!focus?.length) return;
    const ids = focus.filter((f) => visibleIds.has(f));
    if (!ids.length) return;
    const n = neighborhood(ids[0], graph.edges, 1);
    ids.forEach((i) => n.add(i));
    setWhy(n); setSelected(ids[0]);
    setTimeout(() => flow.fitView({ nodes: [...n].filter((i) => visibleIds.has(i)).map((id) => ({ id })), duration: 500, padding: 0.3 }), 50);
  }, [focus]);

  const nodes: Node[] = visibleNodes.map((n: any) => ({
    id: n.id, type: "x", position: pos[n.id] || base[n.id] || { x: 0, y: 0 },
    data: { ...n, dim: why ? !why.has(n.id) : false, selected: n.id === selected, highlight: focus?.includes(n.id) },
  }));
  const edges: Edge[] = graph.edges.filter((e: any) => visibleIds.has(e.source) && visibleIds.has(e.target)).map((e: any) => {
    const r = REL[e.relationship] || REL.RELATED_TO;
    const dim = why ? !(why.has(e.source) && why.has(e.target)) : false;
    const inferred = e.method === "llm";
    return {
      id: e.id, source: e.source, target: e.target,
      label: (!dim && (r.label && (why || e.relationship === "CONTRADICTS"))) ? r.label + (inferred ? " (inferred)" : "") : undefined,
      labelStyle: { fontSize: 10, fill: r.color }, animated: e.relationship === "CONTRADICTS" && !dim,
      style: { stroke: r.color, strokeDasharray: inferred ? "4 4" : r.dash, strokeWidth: e.relationship === "SUPPORTS" || e.relationship === "CONTRADICTS" ? 1.8 : 1, opacity: dim ? 0.06 : 0.9 },
      markerEnd: { type: MarkerType.ArrowClosed, color: r.color, width: 12, height: 12 }, data: e,
    };
  });

  const sel = graph.nodes.find((n: any) => n.id === selected);
  const connected = sel ? graph.edges.filter((e: any) => e.source === sel.id || e.target === sel.id) : [];
  const label = (id: string) => graph.nodes.find((n: any) => n.id === id)?.label || id;

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
      <div className="relative h-[620px] overflow-hidden rounded-xl border bg-slate-50/60">
        <div className="absolute left-2 top-2 z-10 flex max-w-[75%] flex-wrap gap-1">
          {Object.entries(TYPE).map(([t, v]) => (
            <button key={t} onClick={() => setTypes({ ...types, [t]: !types[t] })} aria-pressed={!!types[t]}
              className={`chip border ${types[t] ? "border-slate-300 bg-white text-slate-700" : "border-transparent bg-slate-200/70 text-slate-400 line-through"}`}>
              <span aria-hidden>{v.glyph}</span>{v.label}
            </button>
          ))}
        </div>
        <div className="absolute right-2 top-2 z-10 flex gap-1">
          {why && <button className="btn-ghost bg-white shadow-sm" onClick={() => { setWhy(null); }}>Show everything</button>}
          <button className="btn-ghost bg-white shadow-sm" onClick={() => { setPos({}); setWhy(null); setSelected(null); flow.fitView({ duration: 400 }); }}>Reset</button>
        </div>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.1} maxZoom={2}
          onNodeClick={(_, n) => { setSelected(n.id); setEdgeSel(null); }}
          onEdgeClick={(_, e) => { setEdgeSel(e.data); setSelected(null); }}
          onNodeDragStop={(_, n) => setPos({ ...pos, [n.id]: n.position })}
          onPaneClick={() => { setSelected(null); setEdgeSel(null); }} proOptions={{ hideAttribution: true }}>
          <Background gap={24} color="#e2e8f0" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable nodeColor={(n: any) => n.data?.type === "claim" ? "#f43f5e" : n.data?.type === "gap" ? "#f59e0b" : n.data?.type === "issue" ? "#dc2626" : "#cbd5e1"} />
        </ReactFlow>
      </div>

      <aside className="card max-h-[620px] overflow-auto p-4 text-sm">
        {!sel && !edgeSel && (
          <div className="space-y-3 text-slate-600">
            <div className="font-semibold text-slate-800">How to read this</div>
            <p>Evidence flows left to right: documents and notes → facts → propositions and issues → people.</p>
            <p>Select a proposition, injury or fact and press <b>Show Me Why</b> to isolate the chain behind it.</p>
            <div className="space-y-1 text-xs">
              {Object.entries(REL).filter(([k]) => ["SUPPORTS", "CONTRADICTS", "MISSING_EVIDENCE_FOR", "EVIDENCE_FOR", "TREATED_BY"].includes(k)).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2">
                  <svg width="34" height="6"><line x1="0" y1="3" x2="34" y2="3" stroke={v.color} strokeWidth="2" strokeDasharray={v.dash} /></svg>
                  {k.replace(/_/g, " ").toLowerCase()}
                </div>
              ))}
              <div className="flex items-center gap-2"><svg width="34" height="6"><line x1="0" y1="3" x2="34" y2="3" stroke="#64748b" strokeWidth="2" strokeDasharray="4 4" /></svg>inferred by AI (needs review)</div>
              <div>✓ verified · △ needs review · ≠ conflicting · ? gap · NEW = since last build</div>
            </div>
          </div>
        )}
        {sel && (
          <div className="space-y-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-rose-600">{TYPE[sel.type]?.label}</div>
            <div className="font-semibold">{sel.label}</div>
            {sel.state_label && <div className="chip bg-rose-50 text-rose-800">{sel.state_label}</div>}
            {sel.detail && <div className="text-xs text-slate-500">{sel.detail}</div>}
            {sel.date && <div className="text-xs text-slate-500">{fmtDate(sel.date)}</div>}
            {sel.status === "needs_review" && <div className="chip bg-amber-100 text-amber-800">△ Needs review</div>}
            <div className="flex flex-wrap gap-1">
              <button className="btn-primary" onClick={() => { const n = neighborhood(sel.id, graph.edges); setWhy(n);
                setTimeout(() => flow.fitView({ nodes: [...n].filter((i) => visibleIds.has(i)).map((id) => ({ id })), duration: 500, padding: 0.25 }), 30); }}>
                Show Me Why
              </button>
              {sel.ref?.source_type && <button className="btn-ghost" onClick={() => open(sel.ref)}>Open source</button>}
              {sel.issue_id && onFocusIssue && <button className="btn-ghost" onClick={() => onFocusIssue(sel.issue_id)}>Open issue</button>}
            </div>
            <div className="pt-2 text-xs font-semibold uppercase text-slate-500">Connections ({connected.length})</div>
            <ul className="space-y-1 text-xs">
              {connected.slice(0, 30).map((e: any) => (
                <li key={e.id} className="flex items-start gap-1">
                  <span className="shrink-0 rounded bg-slate-100 px-1 text-[10px]">{e.relationship.replace(/_/g, " ").toLowerCase()}</span>
                  <button className="text-left hover:text-rose-700" onClick={() => setSelected(e.source === sel.id ? e.target : e.source)}>
                    {label(e.source === sel.id ? e.target : e.source)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {edgeSel && (
          <div className="space-y-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-rose-600">Relationship</div>
            <div className="font-semibold">{edgeSel.relationship.replace(/_/g, " ").toLowerCase()}</div>
            <div className="text-xs">{label(edgeSel.source)} <b>→</b> {label(edgeSel.target)}</div>
            <div className="text-xs text-slate-500">{edgeSel.method === "llm" ? "Inferred by AI, then checked against facts" : "Derived from the case data"} · {edgeSel.verify_status === "verified" ? "✓ verified" : "△ needs review"}</div>
            <div className="flex flex-wrap gap-1">
              {[edgeSel.source, edgeSel.target].map((id: string) => {
                const n = graph.nodes.find((x: any) => x.id === id);
                return n?.ref?.source_type ? <Cite key={id} src={n.ref} label={`open ${TYPE[n.type]?.label.toLowerCase()}`} /> : null;
              })}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

export default function FullNetwork(props: { graph: any; focus: string[] | null; onFocusIssue?: (id: string) => void }) {
  return <ReactFlowProvider><Inner {...props} /></ReactFlowProvider>;
}
