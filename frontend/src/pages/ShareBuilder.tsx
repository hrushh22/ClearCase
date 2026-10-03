import { useEffect, useMemo, useState } from "react";
import { Check, Copy, ExternalLink, Eye, EyeOff, Hospital, Link2, Lock, Send, ShieldOff, Sparkles, Stethoscope, UserRound } from "lucide-react";
import ProviderView, { type ProviderClaim } from "../components/ProviderView";
import { Cite } from "../components/SourceViewer";
import { SectionHeader } from "../components/ui";
import { api, appUrl, fmtDateTime } from "../lib/api";

const CAT_LABEL: Record<string, string> = {
  status: "Status", treatment: "Treatment", bills: "Bills", needs: "Firm needs", coverage: "Coverage",
  provider_facts: "Records", strategy: "Strategy", other_providers: "Other providers",
};

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? "grad-bg" : "bg-slate-200"}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
    </button>
  );
}

function Step({ n, title, active, done }: { n: number; title: string; active: boolean; done: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold transition ${done ? "bg-emerald-500 text-white" : active ? "grad-bg text-white shadow" : "bg-rose-50 text-rose-400"}`}>
        {done ? <Check size={14} /> : n}
      </span>
      <span className={`text-sm font-medium ${active || done ? "text-slate-900" : "text-slate-400"}`}>{title}</span>
    </div>
  );
}

export default function ShareBuilder({ d }: { d: any }) {
  const [providers, setProviders] = useState<any[]>([]);
  const [pid, setPid] = useState<string>("");
  const [prop, setProp] = useState<any>(null);
  const [on, setOn] = useState<Record<string, boolean>>({});
  const [links, setLinks] = useState<any[]>([]);
  const [created, setCreated] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(30);
  const [copied, setCopied] = useState(false);

  const refreshLinks = () => api.links().then(setLinks);
  useEffect(() => { api.providers().then((p) => { setProviders(p); if (p[0]) setPid(p[0].id); }); refreshLinks(); }, []);
  useEffect(() => {
    if (!pid) return;
    setLoading(true); setCreated(null);
    api.proposal(pid).then((p) => {
      setProp(p);
      setOn(Object.fromEntries(p.candidates.map((c: any) => [c.id, c.suggested === "share"])));
    }).finally(() => setLoading(false));
  }, [pid, d.content_hash]);

  const provider = providers.find((p) => p.id === pid);
  const preview: ProviderClaim[] = useMemo(() => (prop?.candidates || []).filter((c: any) => on[c.id])
    .map((c: any) => ({ id: c.id, text: c.text, category: c.category, verified: "preview" as const })), [prop, on]);
  const wf = prop?.candidates.find((c: any) => c.id === "waterfall_position");
  const share = (prop?.candidates || []).filter((c: any) => c.suggested === "share");
  const hold = (prop?.candidates || []).filter((c: any) => c.suggested !== "share");

  const send = async () => {
    const r = await api.createLink({ provider_id: pid, approved_ids: Object.keys(on).filter((k) => on[k]), days });
    setCreated({ ...r, url: appUrl(`/p/${r.token}`) });
    refreshLinks();
  };
  const copy = () => { navigator.clipboard?.writeText(created.url); setCopied(true); setTimeout(() => setCopied(false), 1800); };

  const Item = (c: any) => (
    <div key={c.id} className={`flex items-start gap-3 rounded-2xl border p-3 transition ${on[c.id] ? "border-emerald-200 bg-emerald-50/50" : "border-rose-100 bg-white hover:border-rose-200"}`}>
      <Toggle on={!!on[c.id]} onChange={(v) => setOn({ ...on, [c.id]: v })} label={`Share: ${c.text}`} />
      <div className="min-w-0 flex-1 text-sm">
        <div className="text-slate-800">{c.text}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
          <span className="chip bg-slate-100 text-slate-600">{CAT_LABEL[c.category] || c.category}</span>
          <span>{c.reason}</span>
          {c.source && <Cite src={c.source} />}
        </div>
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      <section className="card fade-up overflow-hidden p-0">
        <div className="grad-bg px-6 py-5 text-white">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-white/85"><Link2 size={14} />Share with providers</div>
          <div className="mt-1 text-2xl font-extrabold tracking-tight">Give a treating provider live, signed case status</div>
          <div className="mt-1 max-w-3xl text-sm text-white/90">
            The AI proposes what to share and what to hold back; you decide. The provider sees exactly the preview, every line digitally signed,
            and their link updates itself after every sync.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-6 px-6 py-3">
          <Step n={1} title="Pick a provider" active={!prop} done={!!prop} />
          <span className="h-px w-10 bg-rose-200" />
          <Step n={2} title="Choose what to share" active={!!prop && !created} done={!!created} />
          <span className="h-px w-10 bg-rose-200" />
          <Step n={3} title="Preview, sign and send" active={!!prop && !created} done={!!created} />
        </div>
      </section>

      <section className="card p-5">
        <SectionHeader icon={Hospital} title="1 · Pick a provider" note={`${providers.length} treating providers found in Clio`} />
        <div className="stagger grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {providers.map((p) => {
            const Icon = p.type === "Person" ? UserRound : /hospital|surgical|center/i.test(p.name) ? Hospital : Stethoscope;
            const sel = pid === p.id;
            return (
              <button key={p.id} onClick={() => setPid(p.id)} aria-pressed={sel}
                className={`flex items-start gap-3 rounded-2xl border p-3 text-left transition hover:-translate-y-0.5 hover:shadow-md ${sel ? "border-rose-300 bg-rose-50 ring-2 ring-rose-200" : "border-rose-100 bg-white"}`}>
                <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${sel ? "grad-bg text-white" : "bg-rose-50 text-rose-500"}`}><Icon size={18} /></div>
                <div className="min-w-0"><div className="truncate text-sm font-semibold text-slate-900">{p.name}</div><div className="line-clamp-2 text-xs text-slate-500">{p.relationship}</div></div>
              </button>
            );
          })}
        </div>
      </section>

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <section className="card p-5">
          <SectionHeader icon={Sparkles} title="2 · Choose what to share" note={loading ? "the AI is reviewing the file…" : `proposed by ${prop?.method === "llm" ? "AI" : "rules"} · you decide`} />
          {loading && <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-16" />)}</div>}
          {!loading && prop && (
            <div className="space-y-4">
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-emerald-700"><Eye size={15} />AI suggests sharing · {share.length}</div>
                <div className="space-y-2">{share.map(Item)}</div>
              </div>
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-red-700"><EyeOff size={15} />AI suggests holding back · {hold.length}</div>
                <div className="space-y-2">{hold.map(Item)}</div>
              </div>
              <div className="rounded-2xl bg-sky-50 p-3 text-xs text-sky-900">
                The link stays live: after every sync, shared items that change are re-signed, items that no longer apply are withdrawn, and new
                status, needs, visit and bill items flow in if you shared that category. Anything else needs a new share.
              </div>
            </div>
          )}
        </section>

        <section className="space-y-3 lg:sticky lg:top-24">
          <div className="card p-4">
            <SectionHeader icon={Send} title="3 · Preview, sign and send" />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-slate-600">Link expires in</span>
              <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-xl border border-rose-100 px-2 py-1.5 text-sm outline-none focus:border-rose-300">
                {[7, 30, 90].map((n) => <option key={n} value={n}>{n} days</option>)}
              </select>
              <button className="btn-primary ml-auto" disabled={!preview.length} onClick={send}><Lock size={14} />Sign and create link ({preview.length})</button>
            </div>
            {created && (
              <div className="fade-up mt-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-sm">
                <div className="flex items-center gap-1.5 font-semibold text-emerald-800"><Check size={15} />Link ready: {created.claims} signed claims, expires {fmtDateTime(created.expires_at)}</div>
                <div className="mt-2 flex gap-2">
                  <input readOnly value={created.url} className="min-w-0 flex-1 rounded-xl border border-emerald-200 bg-white px-2 py-1.5 font-mono text-xs" />
                  <button className="btn-ghost bg-white" onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copied" : "Copy"}</button>
                  <a className="btn-ghost bg-white" href={created.url} target="_blank"><ExternalLink size={14} />Open</a>
                </div>
              </div>
            )}
          </div>
          <div>
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-rose-500"><Eye size={13} />Live preview: exactly what {provider?.name} will see</div>
            <div className="max-h-[70vh] overflow-auto rounded-3xl border-2 border-dashed border-rose-200 bg-rose-50/40 p-3">
              <ProviderView firm={d.snapshot.firm_name} provider={provider?.name || ""} claims={preview}
                waterfall={wf && on[wf.id] ? { ...(prop?.waterfall_preview || {}), ...parseWf(wf.text) } : undefined} events={[]} />
            </div>
          </div>
        </section>
      </div>

      <section className="card p-5">
        <SectionHeader icon={Link2} title="Shared links and access log" note={`${links.length} link${links.length === 1 ? "" : "s"}`} />
        {!links.length && <div className="text-sm text-slate-500">No links shared yet.</div>}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {links.map((l) => (
            <div key={l.token} className={`card-lift rounded-2xl border border-rose-100 bg-white p-4 transition ${l.revoked ? "opacity-50" : ""}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0"><div className="truncate font-semibold text-slate-900">{l.provider_name}</div>
                  <div className="text-xs text-slate-500">created {fmtDateTime(l.created_at)}</div></div>
                {l.revoked ? <span className="chip bg-slate-200 text-slate-600"><ShieldOff size={12} />revoked</span>
                  : <span className="chip bg-emerald-50 text-emerald-700"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />live</span>}
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-xl bg-rose-50/70 py-1.5"><div className="text-lg font-bold text-slate-900">{l.claim_count}</div><div className="text-[10px] text-slate-500">signed items</div></div>
                <div className="rounded-xl bg-rose-50/70 py-1.5" title={l.opens.map((o: any) => fmtDateTime(o.opened_at)).join("\n")}>
                  <div className="text-lg font-bold text-slate-900">{l.opens.length}</div><div className="text-[10px] text-slate-500">opens</div></div>
                <div className="rounded-xl bg-rose-50/70 py-1.5" title={(l.updates || []).map((u: any) => u.summary).join("\n")}>
                  <div className="text-lg font-bold text-slate-900">{l.updates?.length || 0}</div><div className="text-[10px] text-slate-500">updates pushed</div></div>
              </div>
              <div className="mt-2 text-xs text-slate-500">
                {l.opens.length ? `last opened ${fmtDateTime(l.opens[0].opened_at)}` : "not opened yet"} · expires {fmtDateTime(l.expires_at)}
                {l.notify_email && <span className="chip ml-1 bg-sky-100 text-sky-800">subscribed</span>}
              </div>
              <div className="mt-3 flex gap-2">
                <a className="btn-ghost border border-rose-100" href={appUrl(`/p/${l.token}`)} target="_blank"><ExternalLink size={14} />Open</a>
                {!l.revoked && <button className="btn-ghost border border-red-100 text-red-600 hover:bg-red-50 hover:text-red-700" onClick={() => api.revoke(l.token).then(refreshLinks)}><ShieldOff size={14} />Revoke</button>}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function parseWf(text: string) {
  const m = text.match(/\$([\d,.]+) is number (\d+) of (\d+)/);
  return m ? { billed: Number(m[1].replace(/,/g, "")), position: Number(m[2]), count: Number(m[3]) } : {};
}
