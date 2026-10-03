import { AlarmClock, BellRing, CalendarDays, Hourglass } from "lucide-react";
import { Cite } from "./SourceViewer";
import { SectionHeader, ShowMore } from "./ui";
import { daysFrom, fmtDate } from "../lib/api";

function Group({ icon: Icon, title, tone, items, limit, render }: any) {
  return (
    <div>
      <div className={`mb-1.5 flex items-center gap-2 text-sm font-semibold ${tone}`}>
        <Icon size={15} aria-hidden />{title}<span className="rounded-full bg-slate-100 px-1.5 text-[11px] text-slate-600">{items.length}</span>
      </div>
      <ShowMore items={items} limit={limit} render={render} />
    </div>
  );
}

export default function Attention({ d }: { d: any }) {
  const a = d.attention;
  return (
    <div className="card space-y-4 p-5">
      <SectionHeader icon={BellRing} title="Needs attention" note={`as of ${fmtDate(a.today)}`} />
      <Group icon={AlarmClock} title="Overdue" tone="text-red-700" items={a.overdue} limit={3} render={(t: any) => (
        <div key={t.source_id} className="flex items-start gap-2 rounded-xl border border-red-100 bg-red-50/70 p-2.5 text-sm transition hover:border-red-200">
          <div className="flex-1">
            <div className="font-medium text-slate-900">{t.title}</div>
            <div className="text-xs font-medium text-red-700">due {fmtDate(t.due)} · {t.days_overdue} days overdue</div>
          </div>
          <Cite src={t} />
        </div>
      )} />
      <Group icon={CalendarDays} title="Coming up" tone="text-amber-700" items={a.upcoming} limit={3} render={(t: any) => (
        <div key={t.source_type + t.source_id} className="row-hover flex items-start gap-2 p-1.5 text-sm">
          <div className="w-14 shrink-0 rounded-lg bg-amber-50 py-1 text-center text-[11px] font-semibold leading-tight text-amber-800">
            {fmtDate(t.due).replace(/, \d{4}/, "")}<div className="font-normal text-amber-600">in {daysFrom(t.due)}d</div>
          </div>
          <div className="flex-1 text-slate-700">{t.title}</div>
          <Cite src={t} />
        </div>
      )} />
      <Group icon={Hourglass} title="Waiting on someone else" tone="text-sky-700" items={a.waiting} limit={3} render={(t: any) => (
        <div key={t.source_id} className="row-hover flex items-start gap-2 p-1.5 text-sm">
          <div className="flex-1">
            <div className="font-medium text-slate-800">{t.waiting_on || t.title}</div>
            <div className="text-xs text-slate-500">{t.waiting_on ? t.title.split(" - ").slice(1).join(" - ") : t.detail?.slice(0, 120)}</div>
          </div>
          <Cite src={t} />
        </div>
      )} />
    </div>
  );
}
