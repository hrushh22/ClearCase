import { useMemo, useState } from "react";
import { Cite } from "./SourceViewer";
import { fmtDate, money } from "../lib/api";

const CAT: Record<string, string> = {
  medical: "bg-rose-500", money: "bg-emerald-500", insurance: "bg-teal-500", negotiation: "bg-violet-500", deadline: "bg-amber-500",
  court: "bg-indigo-500", client: "bg-sky-500", risk: "bg-red-600", other: "bg-slate-400",
};

const toDay = (s: string) => Math.floor(new Date(s + "T12:00:00").getTime() / 86400000);
const fromDay = (n: number) => new Date(n * 86400000).toISOString().slice(0, 10);

/** Milestone timeline + time-travel: state of the case at any date = facts dated on or before it. */
export default function Timeline({ d }: { d: any }) {
  const events: any[] = d.timeline.events;
  const [all, setAll] = useState(false);
  const days = events.map((e) => toDay(e.date));
  const min = Math.min(...days), max = Math.max(...days, toDay(new Date().toISOString().slice(0, 10)));
  const [t, setT] = useState<number>(toDay(new Date().toISOString().slice(0, 10)));
  const at = fromDay(t);
  const [cat, setCat] = useState<string | null>(null);

  const shown = useMemo(() => {
    const list = events.filter((e) => (all ? true : e.milestone) && (!cat || e.category === cat));
    return list.slice().reverse();
  }, [events, all, cat]);

  const state = useMemo(() => {
    const past = events.filter((e) => e.date <= at);
    const windowStart = fromDay(t - 120);
    const treating = new Set<string>();
    past.filter((e) => e.category === "medical" && e.date >= windowStart).forEach((e) => treating.add(e.entity || e.text.slice(0, 50)));
    const owed: Record<string, number> = {};
    past.filter((e) => (e.type === "bill" || e.type === "lien") && e.amount && e.entity && e.source_type !== "custom_field")
      .forEach((e) => { owed[e.entity] = e.amount; });
    const upcoming = events.filter((e) => e.date > at && (e.type === "deadline" || e.category === "court")).slice(0, 4);
    const last = past.filter((e) => e.milestone).slice(-4).reverse();
    return { count: past.length, treating: [...treating].slice(0, 6), owed: Object.values(owed).reduce((a, b) => a + b, 0), upcoming, last };
  }, [events, at, t]);

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="card-h">Timeline · every date links to its source</div>
        <div className="flex flex-wrap gap-1">
          {Object.keys(CAT).map((c) => (
            <button key={c} onClick={() => setCat(cat === c ? null : c)}
              className={`chip ${cat === c ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600"}`}>
              <span className={`h-2 w-2 rounded-full ${CAT[c]}`} />{c}
            </button>
          ))}
          <button className="chip bg-indigo-50 text-indigo-700" onClick={() => setAll(!all)}>{all ? "Milestones only" : `All ${events.length} dated facts`}</button>
        </div>
      </div>

      <div className="mt-4 rounded-xl bg-slate-50 p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">Time travel: the case as of <b className="text-indigo-700">{fmtDate(at)}</b></span>
          <button className="chip bg-white text-slate-600" onClick={() => setT(toDay(new Date().toISOString().slice(0, 10)))}>today</button>
        </div>
        <input type="range" min={min} max={max} value={t} onChange={(e) => setT(Number(e.target.value))} className="mt-2 w-full accent-indigo-600" />
        <div className="mt-2 grid gap-3 text-sm md:grid-cols-4">
          <div><div className="card-h">Known facts</div><div className="text-xl font-semibold">{state.count}</div></div>
          <div><div className="card-h">Owed to providers (bills seen so far)</div><div className="text-xl font-semibold">{money(state.owed)}</div></div>
          <div className="md:col-span-2"><div className="card-h">Medical activity in prior 120 days</div>
            <div className="text-xs text-slate-700">{state.treating.length ? state.treating.join(" · ") : "none recorded"}</div></div>
        </div>
        <div className="mt-2 grid gap-3 text-xs md:grid-cols-2">
          <div><span className="font-semibold text-slate-600">Most recent milestones then: </span>{state.last.map((e) => e.milestone).join(" · ") || "—"}</div>
          <div><span className="font-semibold text-slate-600">Coming up after that date: </span>{state.upcoming.map((e) => `${fmtDate(e.date)} ${e.text.slice(0, 50)}`).join(" · ") || "—"}</div>
        </div>
      </div>

      <div className="relative mt-4 max-h-[520px] overflow-auto pl-6">
        <div className="absolute bottom-0 left-2 top-0 w-0.5 bg-slate-200" />
        {shown.map((e) => {
          const future = e.date > at;
          return (
            <div key={e.fact_id} className={`relative flex items-start gap-3 py-1.5 ${future ? "opacity-35" : ""}`}>
              <span className={`absolute -left-[19px] top-3 h-2.5 w-2.5 rounded-full ring-2 ring-white ${CAT[e.category] || CAT.other}`} />
              <div className="w-24 shrink-0 text-xs tabular-nums text-slate-500">{fmtDate(e.date)}</div>
              <div className="flex-1 text-sm">
                {e.milestone && <span className="font-semibold">{e.milestone}. </span>}
                <span className={e.milestone ? "text-slate-600" : ""}>{e.text}</span>
                {e.amount ? <span className="ml-1 font-medium text-emerald-700">{money(e.amount)}</span> : null}
                {e.verify_status === "partial" && <span className="chip ml-1 bg-amber-100 text-amber-800">partly supported</span>}
              </div>
              <Cite src={e} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
