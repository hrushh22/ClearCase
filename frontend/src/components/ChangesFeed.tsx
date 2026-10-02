import { useMemo, useState } from "react";
import { Cite } from "./SourceViewer";
import { fmtDate, fmtDateTime, SOURCE_LABEL } from "../lib/api";

const WINDOWS = [
  { key: "visit", label: "Since my last visit" },
  { key: "7", label: "Last 7 days" },
  { key: "30", label: "Last 30 days" },
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

  const recent = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    const seen = new Set<string>();
    return (d.timeline.events as any[])
      .filter((e) => e.date && e.date >= since && e.date <= today && e.source_type !== "custom_field")
      .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
      .filter((e) => {
        const k = `${e.source_type}:${e.source_id}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      })
      .slice(0, 12);
  }, [d, since]);

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="card-h">What changed since you last opened</div>
        <div className="flex gap-1">
          {WINDOWS.map((w) => (
            <button key={w.key} onClick={() => setWin(w.key)}
              className={`chip ${win === w.key ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>{w.label}</button>
          ))}
        </div>
      </div>
      <div className="mt-1 text-xs text-slate-500">
        {ch.last_viewed_at ? `Your last visit: ${fmtDateTime(ch.last_viewed_at)}` : "First visit on this machine; showing recent activity."}
        {" · "}showing activity dated on or after {fmtDate(since)}
      </div>
      {ch.items?.length > 0 && (
        <div className="mt-3 space-y-1.5 rounded-lg bg-indigo-50 p-3">
          <div className="text-xs font-semibold text-indigo-800">Digest changes since your last visit</div>
          {ch.items.slice(0, 8).map((it: any, i: number) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <span className="chip bg-white text-indigo-700">{it.kind.replace("_", " ")}</span>
              <span className="flex-1">{it.summary}</span>
              <Cite src={it.source} />
            </div>
          ))}
        </div>
      )}
      <div className="mt-3 divide-y">
        {recent.length === 0 && <div className="py-3 text-sm text-slate-500">Nothing new in this window.</div>}
        {recent.map((e) => (
          <div key={e.fact_id} className="flex items-start gap-3 py-2 text-sm">
            <div className="w-20 shrink-0 text-xs tabular-nums text-slate-500">{fmtDate(e.date)}</div>
            <div className="flex-1">
              <span className="mr-1 text-xs text-slate-400">{SOURCE_LABEL[e.source_type]}</span>
              {e.text}
            </div>
            <Cite src={e} />
          </div>
        ))}
      </div>
    </div>
  );
}
