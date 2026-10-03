import { Activity, HeartPulse, Info, UserRound } from "lucide-react";
import { Cite } from "./SourceViewer";
import { SectionHeader, ShowMore } from "./ui";

export default function Injuries({ d }: { d: any }) {
  const inj = d.injuries;
  const scanned = d.documents.filter((x: any) => x.scanned_pages > 0).reduce((a: number, x: any) => a + x.scanned_pages, 0);
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="card p-5 lg:col-span-2">
        <SectionHeader icon={HeartPulse} title="Injuries and treatment"
          note={`from ${d.documents.length} documents (${scanned} scanned pages read by OCR) · ${inj.method === "llm" ? "AI summary, every line cited" : "diagnosis lines found by rules"}`} />
        {d.ai_coverage?.sampled_docs?.length > 0 && (
          <div className="mb-3 flex items-center gap-1.5 rounded-xl bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
            <Info size={13} />Free-tier limit: AI read the first and last pages of {d.ai_coverage.sampled_docs.length} long documents. Every page is still searchable.
          </div>
        )}
        <ShowMore items={inj.injuries} limit={4} className="stagger grid gap-3 md:grid-cols-2"
          empty={<div className="text-sm text-slate-500">No injury facts yet.</div>}
          render={(i: any, k: number) => (
            <div key={k} className="card-lift rounded-2xl border border-rose-100 bg-white p-4 transition">
              {i.body_part && <div className="mb-1 flex items-center gap-1.5 font-semibold text-rose-600"><Activity size={15} />{i.body_part}</div>}
              <div className="text-sm text-slate-800">{i.finding}</div>
              {i.treatment && <div className="mt-1 text-sm text-slate-600"><span className="font-medium text-slate-700">Treatment:</span> {i.treatment}</div>}
              {i.status && <div className="mt-1 text-xs text-slate-500">Status: {i.status}</div>}
              <div className="mt-2 flex flex-wrap gap-1">{i.sources.slice(0, 4).map((s: any, j: number) => <Cite key={j} src={s} />)}</div>
            </div>
          )} />
      </div>
      <div className="card p-5">
        <SectionHeader icon={UserRound} title="Who treated" />
        <ShowMore items={inj.providers || []} limit={6} render={(p: any, k: number) => (
          <div key={k} className="row-hover flex items-start gap-2 p-2 text-sm">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-rose-50 text-xs font-bold text-rose-600">
              {(p.name || "?").replace(/^Dr\.?\s*/, "").slice(0, 1)}
            </div>
            <div className="flex-1"><div className="font-medium text-slate-800">{p.name}</div><div className="text-xs text-slate-500">{p.role}</div></div>
            {p.sources?.[0] && <Cite src={p.sources[0]} />}
          </div>
        )} />
      </div>
    </div>
  );
}
