import { Cite } from "./SourceViewer";
import { daysFrom, fmtDate } from "../lib/api";

function Group({ title, tone, items, render }: any) {
  return (
    <div>
      <div className={`mb-1 flex items-center gap-2 text-sm font-semibold ${tone}`}>
        {title} <span className="chip bg-slate-100 text-slate-600">{items.length}</span>
      </div>
      {items.length === 0 && <div className="text-xs text-slate-400">None</div>}
      <div className="space-y-1.5">{items.map(render)}</div>
    </div>
  );
}

export default function Attention({ d }: { d: any }) {
  const a = d.attention;
  return (
    <div className="card space-y-4 p-5">
      <div className="card-h">Needs attention · as of {fmtDate(a.today)}</div>
      <Group title="Overdue" tone="text-rose-700" items={a.overdue} render={(t: any) => (
        <div key={t.source_id} className="flex items-start gap-2 rounded-lg bg-rose-50 p-2 text-sm">
          <div className="flex-1">
            <div className="font-medium">{t.title}</div>
            <div className="text-xs text-rose-700">due {fmtDate(t.due)} · {t.days_overdue} days overdue</div>
          </div>
          <Cite src={t} />
        </div>
      )} />
      <Group title="Coming up (7 days tasks, 14 days calendar)" tone="text-amber-700" items={a.upcoming} render={(t: any) => (
        <div key={t.source_type + t.source_id} className="flex items-start gap-2 text-sm">
          <div className="w-16 shrink-0 text-xs tabular-nums text-slate-500">{fmtDate(t.due).replace(/, \d{4}/, "")}<br />
            <span className="text-slate-400">in {daysFrom(t.due)}d</span></div>
          <div className="flex-1">{t.title}</div>
          <Cite src={t} />
        </div>
      )} />
      <Group title="Waiting on someone else" tone="text-sky-700" items={a.waiting} render={(t: any) => (
        <div key={t.source_id} className="flex items-start gap-2 text-sm">
          <div className="flex-1">
            <div>{t.waiting_on ? <b>{t.waiting_on}</b> : t.title}</div>
            <div className="text-xs text-slate-500">{t.waiting_on ? t.title.split(" - ").slice(1).join(" - ") : t.detail?.slice(0, 120)}</div>
          </div>
          <Cite src={t} />
        </div>
      )} />
    </div>
  );
}
