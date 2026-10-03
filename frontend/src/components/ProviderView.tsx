import { useState } from "react";
import { StageBar, TRACKER } from "./Tracker";
import { fmtDate, fmtDateTime, money } from "../lib/api";

export type ProviderClaim = { id: string; text: string; category: string; verified: "ok" | "bad" | "preview"; issued_at?: string; fresh?: boolean };

const SECTIONS: { cat: string; title: string }[] = [
  { cat: "needs", title: "What the firm needs from your office" },
  { cat: "treatment", title: "Your patient's schedule" },
  { cat: "bills", title: "Your bills and place in line" },
  { cat: "coverage", title: "Coverage behind the case" },
  { cat: "provider_facts", title: "Records and activity involving your office" },
  { cat: "status", title: "Case status" },
  { cat: "strategy", title: "Other information" },
  { cat: "other_providers", title: "Other information" },
];

function Badge({ c, firm }: { c: ProviderClaim; firm: string }) {
  return <span className="inline-flex flex-wrap items-center gap-1">{c.fresh && <span className="chip bg-sky-600 text-white">Updated</span>}<BadgeInner c={c} firm={firm} /></span>;
}

function BadgeInner({ c, firm }: { c: ProviderClaim; firm: string }) {
  if (c.verified === "preview") return <span className="chip bg-slate-100 text-slate-500">preview · signed when sent</span>;
  if (c.verified === "ok")
    return <span className="chip bg-emerald-100 text-emerald-800" title="Digital signature checked in your browser">✓ Verified by {firm}, as of {fmtDateTime(c.issued_at)}</span>;
  return <span className="chip bg-red-100 text-red-800">✕ Could not verify</span>;
}

/** Exactly what a provider sees. Used for the live preview and the real portal. */
export default function ProviderView({ firm, provider, claims, waterfall, events, onSubscribe, subscribed }: {
  firm: string; provider: string; claims: ProviderClaim[]; waterfall?: any; events?: any[];
  onSubscribe?: (email: string) => void; subscribed?: string | null;
}) {
  const [email, setEmail] = useState("");
  const stageClaim = [...claims].reverse().find((c) => c.text.startsWith("Current stage:"));
  const stageIdx = stageClaim ? TRACKER.findIndex((s) => stageClaim.text.includes(s)) : -1;
  const statusClaim = claims.find((c) => c.text.startsWith("The case is"));
  const alive = statusClaim ? statusClaim.text.includes("open and active") : null;
  const lastMove = claims.find((c) => c.text.startsWith("Last case activity"));
  const rest = claims.filter((c) => c !== stageClaim && c !== statusClaim && c !== lastMove && !c.text.startsWith("Current stage:"));

  return (
    <div className="space-y-4">
      <div className="card fade-up overflow-hidden p-0">
        <div className="grad-bg px-5 py-4 text-white">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/85">Case status shared by {firm} with {provider}</div>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            {alive === null ? <span className="text-white/90">Status not shared</span> : (
              <span className="text-2xl font-extrabold tracking-tight drop-shadow-sm">{alive ? "Case is active" : "Case is no longer active"}</span>
            )}
            {statusClaim && <span className="rounded-full bg-white/95 p-0.5"><Badge c={statusClaim} firm={firm} /></span>}
          </div>
        </div>
        <div className="p-5">
        {stageClaim && (
          <div className="mt-1">
            <StageBar index={stageIdx} />
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              <span>{stageClaim.text}</span><Badge c={stageClaim} firm={firm} />
            </div>
          </div>
        )}
        {lastMove && <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-600">{lastMove.text} <Badge c={lastMove} firm={firm} /></div>}
        {!stageClaim && !lastMove && <div className="text-sm text-slate-500">The firm has not shared the case stage.</div>}
        </div>
      </div>

      {waterfall && (
        <div className="card card-lift p-5">
          <div className="card-h">Your place in the payment line</div>
          <div className="mt-3 flex items-end gap-1">
            {Array.from({ length: waterfall.count }).map((_, i) => (
              <div key={i} className={`flex-1 rounded-t ${i + 1 === waterfall.position ? "bg-rose-600" : "bg-slate-200"}`}
                style={{ height: i + 1 === waterfall.position ? 64 : 28 }} title={i + 1 === waterfall.position ? "Your office" : "Another payee (amount private)"} />
            ))}
          </div>
          <div className="mt-2 text-sm">Your balance <b>{money(waterfall.billed, 2)}</b> is number <b>{waterfall.position}</b> of {waterfall.count}. Other payees' amounts are private.</div>
        </div>
      )}

      {SECTIONS.map(({ cat, title }) => {
        const items = rest.filter((c) => c.category === cat);
        if (!items.length) return null;
        return (
          <div key={cat} className="card p-5">
            <div className="card-h">{title}</div>
            <ul className="mt-2 space-y-2">
              {items.map((c) => (
                <li key={c.id} className="flex flex-wrap items-start justify-between gap-2 text-sm">
                  <span className="flex-1">{c.text}</span><Badge c={c} firm={firm} />
                </li>
              ))}
            </ul>
          </div>
        );
      })}

      {events && (
        <div className="card card-lift p-5">
          <div className="card-h">Case movement</div>
          {events.length === 0 && <div className="mt-1 text-sm text-slate-500">No movement since this link was shared. This page updates itself when the case moves.</div>}
          <ul className="mt-1 space-y-1">
            {events.map((e, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <span className="w-24 shrink-0 text-xs tabular-nums text-slate-500">{fmtDateTime(e.created_at)}</span>
                <span className={e.summary.startsWith("No longer") ? "text-slate-500 line-through decoration-slate-300" : ""}>{e.summary}</span>
              </li>
            ))}
          </ul>
          {onSubscribe && (
            <form className="mt-3 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); onSubscribe(email); }}>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@yourpractice.com"
                className="flex-1 rounded-xl border border-rose-100 px-3 py-2 text-sm outline-none focus:border-rose-300 focus:ring-4 focus:ring-rose-100" />
              <button className="btn-primary">Tell me when the case moves</button>
            </form>
          )}
          {subscribed && <div className="mt-2 text-xs text-emerald-700">{subscribed}</div>}
        </div>
      )}
    </div>
  );
}
