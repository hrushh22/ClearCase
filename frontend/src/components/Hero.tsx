import { useState } from "react";
import { BadgeCheck, CalendarClock, ChevronDown, Coins, Landmark, Phone, ShieldCheck, Stethoscope, TriangleAlert, Wallet } from "lucide-react";
import { Cite } from "./SourceViewer";
import { daysFrom, fmtDate, money } from "../lib/api";

/** The first thing on screen: who the client is, where the case stands, and the four numbers that matter.
 *  Details (coverage layers, sources, notes) sit behind "Details" so the hero stays calm. */
export default function Hero({ d }: { d: any }) {
  const [open, setOpen] = useState(false);
  const s = d.snapshot, c = s.client, contact = d.contact, k = d.kpis, cov = k.coverage;
  const initials = (c.name || "?").split(" ").map((p: string) => p[0]).join("").slice(0, 2);
  const sol = daysFrom(s.statute_of_limitations);
  const gap = k.case_value.value && cov.value ? k.case_value.value - cov.value : null;
  const tiles = [
    { icon: Coins, label: "Estimated case value", value: money(k.case_value.value), sub: k.case_value.basis, src: k.case_value.sources },
    { icon: ShieldCheck, label: "Coverage behind it", value: cov.value ? money(cov.value) : cov.kind === "self_insured" ? "Self-insured" : "Unknown",
      sub: cov.confirmed ? "Confirmed in writing" : "Not confirmed", src: cov.sources,
      badge: gap !== null && gap > 0 ? `Value exceeds coverage by ${money(gap)}` : null },
    { icon: Stethoscope, label: "Medical specials", value: money(k.specials.value),
      sub: `${k.specials.providers.filter((p: any) => p.kind === "bill").length} provider bills`, src: k.specials.sources },
    { icon: Wallet, label: "Firm has spent", value: money(k.firm_spend.value), sub: `${k.firm_spend.count} expense entries`, src: k.firm_spend.sources },
  ];
  return (
    <section className="card fade-up overflow-hidden p-0">
      <div className="grad-bg relative px-6 pb-20 pt-6 text-white">
        <div className="pointer-events-none absolute -right-16 -top-24 h-72 w-72 rounded-full bg-white/10 blur-2xl" />
        <div className="relative flex flex-wrap items-center gap-5">
          <div className="relative">
            {c.photo ? (
              <img src={c.photo.data_url} alt={c.name} className="h-24 w-24 rounded-2xl object-cover ring-4 ring-white/40 shadow-lg" />
            ) : (
              <div className="flex h-24 w-24 items-center justify-center rounded-2xl bg-white/20 text-3xl font-bold">{initials}</div>
            )}
            {c.photo && <Cite src={c.photo.source} label="ID scan" className="absolute -bottom-2 left-1/2 -translate-x-1/2" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-3xl font-extrabold tracking-tight drop-shadow-sm">{c.name}</h1>
              <span className="chip bg-white/25 text-white backdrop-blur"><BadgeCheck size={12} />{s.status}</span>
              {s.clio_stage && <span className="chip bg-white text-rose-600">{s.clio_stage}</span>}
            </div>
            <div className="mt-0.5 text-white/90">{s.title}</div>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-white/90">
              <span>Matter <b className="text-white">{s.display_number || s.matter_id}</b></span>
              {s.incident && <span className="inline-flex items-center gap-1">Incident <b className="text-white">{fmtDate(s.incident.date)}</b> <Cite src={s.incident.source} label="field" /></span>}
              <span>Opened <b className="text-white">{fmtDate(s.open_date)}</b></span>
              {s.statute_of_limitations && <span>SOL <b className="text-white">{fmtDate(s.statute_of_limitations)}</b>{sol !== null && sol < 0 && " (passed, see task)"}</span>}
              <span>Attorney <b className="text-white">{s.responsible_attorney || "not set"}</b></span>
            </div>
          </div>
          <div className="min-w-[230px] rounded-2xl bg-white/15 p-3.5 backdrop-blur-md ring-1 ring-white/25">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-white/80"><Phone size={12} />Last real contact</div>
            {contact.last ? (
              <>
                <div className="mt-1 text-xl font-bold">{contact.days_since === 0 ? "Today" : `${contact.days_since} days ago`}<span className="ml-1 text-sm font-normal text-white/80">· {contact.last.channel}</span></div>
                <div className="flex items-center gap-1 text-sm text-white/90"><span className="truncate">{contact.last.title}</span><Cite src={contact.last} label="open" /></div>
              </>
            ) : <div className="mt-1 text-sm text-white/80">No client communications found</div>}
          </div>
        </div>
      </div>

      <div className="relative -mt-14 px-4 pb-4">
        <div className="stagger grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {tiles.map((t) => (
            <div key={t.label} className="card card-lift p-4">
              <div className="flex items-center justify-between">
                <div className="card-h">{t.label}</div>
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-rose-50 text-rose-500"><t.icon size={17} /></div>
              </div>
              <div className="mt-1 text-3xl font-extrabold tracking-tight text-slate-900">{t.value}</div>
              <div className="mt-0.5 text-sm text-slate-500">{t.sub}</div>
              {t.badge && <div className="chip mt-2 bg-red-50 text-red-700"><TriangleAlert size={12} />{t.badge}</div>}
              <div className="mt-2 flex flex-wrap gap-1">{(t.src || []).slice(0, 3).map((x: any, i: number) => <Cite key={i} src={x} />)}</div>
            </div>
          ))}
        </div>
        <button onClick={() => setOpen(!open)} className="btn-ghost mx-auto mt-2 flex text-xs" aria-expanded={open}>
          {open ? "Hide details" : "Details: coverage layers, how each number was found"} <ChevronDown size={14} className={`transition ${open ? "rotate-180" : ""}`} />
        </button>
        {open && (
          <div className="fade-up mt-2 grid gap-3 md:grid-cols-3">
            <div className="rounded-2xl bg-rose-50/60 p-4 text-sm">
              <div className="card-h mb-1 flex items-center gap-1"><Landmark size={12} />Coverage layers</div>
              <div className="text-slate-700">{cov.headline}</div>
              <ul className="mt-1 space-y-0.5 text-xs text-slate-600">{(cov.layers || []).map((l: string, i: number) => <li key={i}>• {l}</li>)}</ul>
              <div className="mt-1 text-xs text-slate-500">{cov.basis}</div>
            </div>
            <div className="rounded-2xl bg-rose-50/60 p-4 text-sm">
              <div className="card-h mb-1 flex items-center gap-1"><Stethoscope size={12} />Specials</div>
              <div className="text-slate-700">{k.specials.basis}</div>
              {k.specials.provider_sum > 0 && <div className="text-xs text-slate-600">Provider bills in the file: {money(k.specials.provider_sum)}</div>}
              {k.specials.note && <div className="text-xs text-amber-700">{k.specials.note}</div>}
            </div>
            <div className="rounded-2xl bg-rose-50/60 p-4 text-sm">
              <div className="card-h mb-1 flex items-center gap-1"><CalendarClock size={12} />Client contact</div>
              {contact.last_from_client && <div className="text-slate-700">Last time the client reached out: {fmtDate(contact.last_from_client.date)} <Cite src={contact.last_from_client} label="open" /></div>}
              <div className="text-xs text-slate-500">{contact.count} conversations with the client in the file</div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
