import { MessagesSquare } from "lucide-react";
import { SectionHeader } from "./ui";
import { Cite } from "./SourceViewer";
import { fmtDate } from "../lib/api";

/** Months x (client contacts / all communications). */
export default function Heatmap({ d }: { d: any }) {
  const c = d.contact;
  const rows: any[] = c.heatmap;
  if (!rows.length) return null;
  const first = rows[0].month, last = new Date().toISOString().slice(0, 7);
  const months: string[] = [];
  let [y, m] = first.split("-").map(Number);
  while (`${y}-${String(m).padStart(2, "0")}` <= last) {
    months.push(`${y}-${String(m).padStart(2, "0")}`);
    m++; if (m > 12) { m = 1; y++; }
  }
  const by = Object.fromEntries(rows.map((r) => [r.month, r]));
  const maxAll = Math.max(...rows.map((r) => r.all));
  return (
    <div className="card p-5">
      <SectionHeader icon={MessagesSquare} title="Communication heatmap" note={`${c.count} client contacts · darker = more emails and calls`} />
      <div className="mt-3 flex flex-wrap gap-1">
        {months.map((mo) => {
          const r = by[mo] || { all: 0, client: 0 };
          const a = r.all / maxAll;
          return (
            <div key={mo} title={`${mo}: ${r.all} communications, ${r.client} with the client`}
              className="relative h-7 w-7 rounded" style={{ background: r.all ? `rgba(244,63,94,${0.15 + a * 0.85})` : "#f1f5f9" }}>
              {r.client > 0 && <span className="absolute bottom-0.5 right-0.5 h-1.5 w-1.5 rounded-full bg-amber-400" />}
              {mo.endsWith("-01") && <span className="absolute -top-4 left-0 text-[10px] text-slate-500">{mo.slice(0, 4)}</span>}
            </div>
          );
        })}
      </div>
      <div className="mt-2 text-xs text-slate-500"><span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" /> month with client contact</div>
      <div className="mt-3 space-y-1 text-sm">
        {c.recent.slice(0, 4).map((r: any) => (
          <div key={r.source_id} className="flex items-center gap-2">
            <span className="w-24 text-xs tabular-nums text-slate-500">{fmtDate(r.date)}</span>
            <span className="chip bg-slate-100 text-slate-600">{r.channel} {r.direction}</span>
            <span className="flex-1 truncate">{r.title}</span>
            <Cite src={r} />
          </div>
        ))}
      </div>
    </div>
  );
}
