import { useSource } from "./SourceViewer";
import { fmtDate, SOURCE_LABEL } from "../lib/api";

export default function Top10({ d }: { d: any }) {
  const t = d.top10;
  const open = useSource();
  return (
    <div className="card p-5">
      <div className="flex items-baseline justify-between">
        <div className="card-h">The ten that matter</div>
        <div className="text-xs text-slate-500">
          ranked from {t.considered} notes, emails and tasks · {t.method === "llm" ? "AI-ranked" : "keyword-ranked (no LLM key)"}
        </div>
      </div>
      <ol className="mt-3 space-y-1">
        {t.items.map((it: any, i: number) => (
          <li key={it.source_type + it.source_id}>
            <button onClick={() => open(it)} className="group flex w-full items-start gap-3 rounded-lg p-2 text-left hover:bg-slate-50">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs font-bold text-white">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-medium group-hover:text-indigo-700">{it.title}</span>
                  <span className="text-xs text-slate-400">{SOURCE_LABEL[it.source_type]} · {fmtDate(it.date)}</span>
                </div>
                <div className="text-sm text-slate-600">{it.why_it_matters}</div>
              </div>
              <span className="text-xs tabular-nums text-slate-400">{it.score}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
