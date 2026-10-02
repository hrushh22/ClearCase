import { Cite } from "./SourceViewer";
import { daysFrom, fmtDate } from "../lib/api";

export default function Snapshot({ d }: { d: any }) {
  const s = d.snapshot;
  const c = s.client;
  const contact = d.contact;
  const initials = (c.name || "?").split(" ").map((p: string) => p[0]).join("").slice(0, 2);
  const sol = daysFrom(s.statute_of_limitations);
  const stage = d.stage;
  return (
    <div className="card flex flex-wrap items-center gap-5 p-5">
      <div className="relative">
        {c.photo ? (
          <img src={c.photo.data_url} alt={c.name} className="h-24 w-24 rounded-2xl object-cover ring-4 ring-indigo-50" />
        ) : (
          <div className="flex h-24 w-24 items-center justify-center rounded-2xl bg-indigo-600 text-3xl font-bold text-white">{initials}</div>
        )}
        {c.photo && <Cite src={c.photo.source} label="ID scan" className="absolute -bottom-2 left-1/2 -translate-x-1/2" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-bold tracking-tight">{c.name}</h1>
          <span className={`chip ${stage.alive ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700"}`}>
            {s.status}
          </span>
          {s.clio_stage && <span className="chip bg-indigo-100 text-indigo-800">Clio stage: {s.clio_stage}</span>}
        </div>
        <div className="mt-0.5 text-slate-600">{s.title}</div>
        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-600">
          <span>
            Matter <b className="text-slate-800">{s.display_number || s.matter_id}</b>
          </span>
          {s.incident && (
            <span className="flex items-center gap-1">
              Incident <b className="text-slate-800">{fmtDate(s.incident.date)}</b> <Cite src={s.incident.source} label="field" />
            </span>
          )}
          <span>Opened <b className="text-slate-800">{fmtDate(s.open_date)}</b></span>
          {s.statute_of_limitations && (
            <span>
              SOL <b className="text-slate-800">{fmtDate(s.statute_of_limitations)}</b>
              {sol !== null && sol < 0 && <span className="text-slate-500"> (passed; see task)</span>}
            </span>
          )}
          <span>Responsible attorney <b className="text-slate-800">{s.responsible_attorney || "not set in Clio"}</b></span>
        </div>
      </div>
      <div className="min-w-[220px] rounded-xl bg-slate-50 p-3 text-sm">
        <div className="card-h">Last real contact with client</div>
        {contact.last ? (
          <>
            <div className="mt-1 text-lg font-semibold">
              {contact.days_since === 0 ? "Today" : `${contact.days_since} days ago`}
              <span className="ml-1 text-sm font-normal text-slate-500">· {contact.last.channel}</span>
            </div>
            <div className="flex items-center gap-1 text-slate-600">
              <span className="truncate">{contact.last.title}</span> <Cite src={contact.last} label="open" />
            </div>
            {contact.last_from_client && contact.last_from_client.source_id !== contact.last.source_id && (
              <div className="mt-1 text-xs text-slate-500">
                Last time the client reached out: {fmtDate(contact.last_from_client.date)} <Cite src={contact.last_from_client} label="open" />
              </div>
            )}
          </>
        ) : (
          <div className="mt-1 text-slate-500">No client communications found</div>
        )}
      </div>
    </div>
  );
}
