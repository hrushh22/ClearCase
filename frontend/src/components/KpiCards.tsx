import { Cite } from "./SourceViewer";
import { money } from "../lib/api";

function Big({ label, value, sub, sources, accent, children }: any) {
  return (
    <div className={`card p-5 ${accent}`}>
      <div className="card-h">{label}</div>
      <div className="mt-1 text-4xl font-bold tracking-tight">{value}</div>
      {sub && <div className="mt-1 text-sm text-slate-600">{sub}</div>}
      {children}
      <div className="mt-3 flex flex-wrap gap-1">
        {(sources || []).slice(0, 4).map((s: any, i: number) => <Cite key={i} src={s} />)}
      </div>
    </div>
  );
}

export default function KpiCards({ d }: { d: any }) {
  const k = d.kpis;
  const cov = k.coverage;
  const gap = k.case_value.value && cov.value ? k.case_value.value - cov.value : null;
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Big label="Estimated case value" value={money(k.case_value.value)} sub={k.case_value.basis} sources={k.case_value.sources}
        accent="border-t-4 border-t-indigo-500" />
      <Big label="Coverage behind it" value={cov.value ? money(cov.value) : cov.kind === "self_insured" ? "Self-insured" : "Unknown"}
        sub={cov.headline} sources={cov.sources} accent="border-t-4 border-t-emerald-500">
        <div className="mt-2 flex flex-wrap gap-1">
          <span className={`chip ${cov.confirmed ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
            {cov.confirmed ? "confirmed in writing" : "not confirmed"}
          </span>
          {gap !== null && gap > 0 && <span className="chip bg-rose-100 text-rose-800">value exceeds coverage by {money(gap)}</span>}
        </div>
        {cov.layers?.length > 0 && (
          <ul className="mt-2 space-y-0.5 text-xs text-slate-600">
            {cov.layers.slice(0, 4).map((l: string, i: number) => <li key={i}>• {l}</li>)}
          </ul>
        )}
      </Big>
      <Big label="Medical specials to date" value={money(k.specials.value)} sub={k.specials.basis} sources={k.specials.sources}>
        {k.specials.provider_sum > 0 && (
          <div className="mt-1 text-xs text-slate-500">
            Provider bills found in the file: {money(k.specials.provider_sum)} across {k.specials.providers.filter((p: any) => p.kind === "bill").length} lines
          </div>
        )}
        {k.specials.note && <div className="mt-1 text-xs text-amber-700">{k.specials.note}</div>}
      </Big>
      <Big label="Firm has spent" value={money(k.firm_spend.value)} sub={`${k.firm_spend.count} expense entries in Clio`}
        sources={k.firm_spend.sources} />
    </div>
  );
}
