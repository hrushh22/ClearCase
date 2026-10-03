import { Cite } from "../SourceViewer";

export const STATE: Record<string, { glyph: string; cls: string; bar: string; rank: number }> = {
  well_corroborated: { glyph: "✓✓", cls: "bg-emerald-100 text-emerald-800", bar: "bg-emerald-500", rank: 5 },
  supported: { glyph: "✓", cls: "bg-emerald-50 text-emerald-700", bar: "bg-emerald-400", rank: 4 },
  limited: { glyph: "◌", cls: "bg-slate-100 text-slate-700", bar: "bg-slate-400", rank: 2 },
  incomplete: { glyph: "?", cls: "bg-amber-100 text-amber-800", bar: "bg-amber-400", rank: 2 },
  conflicting: { glyph: "≠", cls: "bg-red-100 text-red-800", bar: "bg-red-500", rank: 1 },
};

/** Proposition support states from countable components only. No percentages, no outcome scores. */
export default function EvidenceCoverage({ props, onFocus }: { props: any[]; onFocus: (ids: string[]) => void }) {
  return (
    <div className="grid gap-2 md:grid-cols-2">
      {props.map((p) => {
        const s = STATE[p.state];
        const c = p.components;
        return (
          <div key={p.id} className="card-lift rounded-2xl border border-rose-100 bg-white p-3 transition">
            <div className="flex items-start gap-2">
              <button className="flex-1 text-left text-sm font-medium hover:text-rose-700" onClick={() => onFocus([p.id])}>{p.title}</button>
              <span className={`chip shrink-0 ${s.cls}`}><span aria-hidden>{s.glyph}</span>{p.state_label}</span>
            </div>
            <div className="mt-2 flex gap-0.5" aria-hidden title={c.rule}>
              {Array.from({ length: Math.min(c.verified_sources, 12) }).map((_, k) => <span key={k} className={`h-1.5 flex-1 rounded ${s.bar}`} />)}
              {Array.from({ length: Math.max(0, 12 - Math.min(c.verified_sources, 12)) }).map((_, k) => <span key={k} className="h-1.5 flex-1 rounded bg-slate-100" />)}
            </div>
            <details className="mt-1 text-xs text-slate-600">
              <summary className="cursor-pointer select-none">
                {c.verified_sources} verified · {c.independent_source_types} source types · {c.contradictions} contradictions · {c.open_gaps} open gaps
              </summary>
              <div className="mt-1 space-y-1">
                <div className="text-slate-500">Rule applied: {c.rule}</div>
                <div className="text-slate-500">Source types: {c.source_types.join(", ") || "none"} · documents: {c.documents} · needs review: {c.needs_review_sources}</div>
                <div className="flex flex-wrap gap-1">{p.evidence.slice(0, 6).map((e: any, k: number) => <Cite key={k} src={e} />)}</div>
              </div>
            </details>
          </div>
        );
      })}
    </div>
  );
}
