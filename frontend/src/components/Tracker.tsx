import { Route } from "lucide-react";
import { SectionHeader } from "./ui";
import { Cite } from "./SourceViewer";
import { fmtDate } from "../lib/api";

export const TRACKER = ["Treatment", "Demand sent", "Negotiation", "Litigation", "Settlement"];

/** Package-tracker style stage bar. `index` -1 = unknown. */
export function StageBar({ index, alive = true }: { index: number; alive?: boolean }) {
  return (
    <div className="flex items-center">
      {TRACKER.map((s, i) => {
        const done = i < index, cur = i === index;
        return (
          <div key={s} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center">
              <div className={`flex h-9 w-9 items-center justify-center rounded-full border-2 text-sm font-bold transition
                ${cur ? "border-rose-600 bg-rose-600 text-white ring-4 ring-rose-100" : done ? "border-rose-600 bg-rose-50 text-rose-700" : "border-slate-300 bg-white text-slate-400"}`}>
                {done ? "✓" : i + 1}
              </div>
              <div className={`mt-1 w-20 text-center text-xs ${cur ? "font-semibold text-rose-700" : "text-slate-500"}`}>{s}</div>
            </div>
            {i < TRACKER.length - 1 && <div className={`mx-1 mb-5 h-1 flex-1 rounded ${i < index ? "bg-rose-600" : "bg-slate-200"}`} />}
          </div>
        );
      })}
      {!alive && <span className="chip ml-3 bg-slate-200 text-slate-700">closed</span>}
    </div>
  );
}

export default function Tracker({ d }: { d: any }) {
  const st = d.stage;
  return (
    <div className="card p-5">
      <SectionHeader icon={Route} title="Where the case is"
        note={<>{st.method === "llm" ? "classified by AI from dated evidence" : "classified from dated evidence (rules)"} · confidence {Math.round((st.confidence || 0) * 100)}%{st.clio_stage && <> · Clio says <b>{st.clio_stage}</b></>}</>} />
      <div className="mt-4">
        {st.index < 0 ? <div className="text-slate-500">Stage unknown: the evidence is too weak to say.</div> : <StageBar index={st.index} alive={st.alive} />}
      </div>
      <div className="mt-3 text-sm text-slate-700">{st.reason}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-slate-500">Last movement:</span>
        <b>{fmtDate(st.last_movement_at)}</b>
        {st.last_movement && <Cite src={st.last_movement} />}
        <span className="ml-3 text-slate-500">Evidence:</span>
        {st.evidence?.slice(0, 4).map((e: any, i: number) => <Cite key={i} src={e} label={fmtDate(e.date)} />)}
      </div>
    </div>
  );
}
