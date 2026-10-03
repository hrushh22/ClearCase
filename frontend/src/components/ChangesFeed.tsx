import { useMemo, useState } from "react";
import { History, Sparkles } from "lucide-react";
import { Cite } from "./SourceViewer";
import { SectionHeader, ShowMore } from "./ui";
import { fmtDate, fmtDateTime, SOURCE_LABEL } from "../lib/api";

const WINDOWS = [
  { key: "visit", label: "Since last visit" },
  { key: "7", label: "7 days" },
  { key: "30", label: "30 days" },
];

/** Digest diff (new facts, KPI and stage changes) plus every record dated after the chosen marker. */
export default function ChangesFeed({ d }: { d: any }) {
  const ch = d.changes || {};
  const [win, setWin] = useState(ch.last_viewed_at ? "visit" : "30");
  const since = useMemo(() => {
    if (win === "visit" && ch.since) return ch.since.slice(0, 10);
    const days = win === "visit" ? 30 : Number(win);
    return new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
  }, [win, ch.since]);

  const pick = (from: string) => {
    const today = new Date().toISOString().slice(0, 10);
    const seen = new Set<string>();
    return (d.timeline.events as any[])
      .filter((e) => e.date && e.date >= from && e.date <= today && e.source_type !== "custom_field")
      .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
      .filter((e) => {
        const k = `${e.source_type}:${e.source_id}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      })
      .slice(0, 12);
  };
  // nothing new since the last visit (e.g. you were here an hour ago): show the last 30 days instead, and say so
  const { recent, fellBack } = useMemo(() => {
    const r = pick(since);
    if (r.length || win !== "visit") return { recent: r, fellBack: false };
    return { recent: pick(new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10)), fellBack: true };
  }, [d, since, win]);

  return (
    <div className="card p-5">
      <SectionHeader icon={History} title="What changed"
        note={ch.last_viewed_at ? `your last visit ${fmtDateTime(ch.last_viewed_at)}` : "recent activity"}>
        <div className="flex rounded-xl bg-rose-50 p-0.5">
          {WINDOWS.map((w) => (
            <button key={w.key} onClick={() => setWin(w.key)} aria-pressed={win === w.key}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${win === w.key ? "bg-white text-rose-700 shadow-sm" : "text-slate-500 hover:text-rose-700"}`}>{w.label}</button>
          ))}
        </div>
      </SectionHeader>
      {ch.items?.length > 0 && (
        <div className="mb-3 space-y-1.5 rounded-xl border border-rose-100 bg-rose-50/60 p-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-700"><Sparkles size={13} />Changes in the case since your last visit</div>
          <ShowMore items={ch.items} limit={3} render={(it: any, i: number) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <span className="chip bg-white text-rose-700">{it.kind.replace("_", " ")}</span>
              <span className="flex-1 text-slate-700">{it.summary}</span>
              <Cite src={it.source} />
            </div>
          )} />
        </div>
      )}
      {fellBack && <div className="mb-2 text-xs text-slate-500">Nothing new since your last visit. Here are the last 30 days.</div>}
      <ShowMore items={recent} limit={6} className="relative space-y-0.5 pl-4"
        empty={<div className="py-3 text-sm text-slate-500">Nothing new since {fmtDate(since)}.</div>}
        render={(e: any) => (
          <div key={e.fact_id} className="row-hover relative flex items-start gap-3 p-1.5 text-sm">
            <span className="absolute -left-3 top-3 h-2 w-2 rounded-full bg-rose-300 ring-4 ring-white" />
            <div className="w-20 shrink-0 text-xs tabular-nums text-slate-500">{fmtDate(e.date)}</div>
            <div className="flex-1 text-slate-700"><span className="mr-1 text-[11px] text-slate-400">{SOURCE_LABEL[e.source_type]}</span>{e.text}</div>
            <Cite src={e} />
          </div>
        )} />
    </div>
  );
}
