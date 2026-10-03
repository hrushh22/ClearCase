import { ChevronRight, ListOrdered } from "lucide-react";
import { useSource } from "./SourceViewer";
import { SectionHeader, ShowMore } from "./ui";
import { fmtDate, SOURCE_LABEL } from "../lib/api";

export default function Top10({ d }: { d: any }) {
  const t = d.top10;
  const open = useSource();
  return (
    <div className="card p-5">
      <SectionHeader icon={ListOrdered} title="The ten that matter"
        note={`ranked from ${t.considered} notes, emails and tasks · ${t.method === "llm" ? "AI-ranked" : "keyword-ranked"}`} />
      <ShowMore items={t.items} limit={5} className="grid gap-1.5 md:grid-cols-2" render={(it: any, i: number) => (
        <button key={it.source_type + it.source_id} onClick={() => open(it)}
          className="row-hover group flex w-full items-start gap-3 border border-transparent p-2.5 text-left hover:border-rose-100">
          <span className="grad-bg mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white shadow-sm">{i + 1}</span>
          <div className="min-w-0 flex-1">
            <div className="font-medium leading-snug text-slate-900 group-hover:text-rose-700">{it.title}</div>
            <div className="mt-0.5 text-sm text-slate-600">{it.why_it_matters}</div>
            <div className="mt-1 text-[11px] text-slate-400">{SOURCE_LABEL[it.source_type]} · {fmtDate(it.date)}</div>
          </div>
          <ChevronRight size={16} className="mt-1 shrink-0 text-rose-300 transition group-hover:translate-x-0.5 group-hover:text-rose-500" aria-hidden />
        </button>
      )} />
    </div>
  );
}
