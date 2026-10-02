import { useEffect, useMemo, useState } from "react";
import ProviderView, { type ProviderClaim } from "../components/ProviderView";
import { Cite } from "../components/SourceViewer";
import { api, fmtDateTime } from "../lib/api";

const CAT_LABEL: Record<string, string> = {
  status: "Status", treatment: "Treatment", bills: "Bills", needs: "Firm needs", coverage: "Coverage",
  provider_facts: "Records", strategy: "Strategy", other_providers: "Other providers",
};

export default function ShareBuilder({ d }: { d: any }) {
  const [providers, setProviders] = useState<any[]>([]);
  const [pid, setPid] = useState<string>("");
  const [prop, setProp] = useState<any>(null);
  const [on, setOn] = useState<Record<string, boolean>>({});
  const [links, setLinks] = useState<any[]>([]);
  const [created, setCreated] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(30);

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

  const send = async () => {
    const r = await api.createLink({ provider_id: pid, approved_ids: Object.keys(on).filter((k) => on[k]), days });
    setCreated({ ...r, url: `${window.location.origin}/p/${r.token}` });
    refreshLinks();
  };

  return (
    <div className="space-y-4">
      <div className="card p-5">
        <div className="text-lg font-semibold">Share case status with a treating provider</div>
        <div className="text-sm text-slate-600">
          The AI proposes what to share and what to hold back. You decide. The provider sees exactly the preview on the right, each line digitally signed by your firm.
          Only claims the verifier could back with a source are offered.
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {providers.map((p) => (
            <button key={p.id} onClick={() => setPid(p.id)}
              className={`rounded-lg border px-3 py-2 text-left text-sm ${pid === p.id ? "border-indigo-500 bg-indigo-50" : "hover:bg-slate-50"}`}>
              <div className="font-medium">{p.name}</div><div className="text-xs text-slate-500">{p.relationship}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-5">
          <div className="flex items-baseline justify-between">
            <div className="card-h">Proposed by {prop?.method === "llm" ? "AI" : "rules"} · you choose</div>
            {loading && <span className="text-xs text-slate-500">thinking…</span>}
          </div>
          <div className="mt-3 space-y-2">
            {prop?.candidates.map((c: any) => (
              <label key={c.id} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${on[c.id] ? "border-emerald-200 bg-emerald-50/50" : "border-slate-200 bg-slate-50/50"}`}>
                <input type="checkbox" className="mt-1" checked={!!on[c.id]} onChange={(e) => setOn({ ...on, [c.id]: e.target.checked })} />
                <div className="flex-1 text-sm">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="chip bg-slate-200 text-slate-700">{CAT_LABEL[c.category] || c.category}</span>
                    <span className={`chip ${c.suggested === "share" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}>
                      AI: {c.suggested}
                    </span>
                    {c.source && <Cite src={c.source} />}
                  </div>
                  <div className="mt-1">{c.text}</div>
                  <div className="text-xs text-slate-500">{c.reason}</div>
                </div>
              </label>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4">
            <span className="text-sm">Link expires in</span>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded border px-2 py-1 text-sm">
              {[7, 30, 90].map((n) => <option key={n} value={n}>{n} days</option>)}
            </select>
            <button className="btn-primary ml-auto" disabled={!preview.length} onClick={send}>Sign and create link ({preview.length} items)</button>
          </div>
          {created && (
            <div className="mt-3 rounded-lg bg-emerald-50 p-3 text-sm">
              Link ready, {created.claims} signed claims, expires {fmtDateTime(created.expires_at)}:
              <div className="mt-1 flex gap-2"><input readOnly value={created.url} className="flex-1 rounded border bg-white px-2 py-1 font-mono text-xs" />
                <a className="btn-ghost" href={created.url} target="_blank">Open as provider</a></div>
            </div>
          )}
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Live preview: exactly what {provider?.name} will see</div>
          <div className="rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 p-3">
            <ProviderView firm={d.snapshot.firm_name} provider={provider?.name || ""} claims={preview}
              waterfall={wf && on[wf.id] ? { ...(prop?.waterfall_preview || {}), ...parseWf(wf.text) } : undefined} events={[]} />
          </div>
        </div>
      </div>

      <div className="card p-5">
        <div className="card-h">Shared links and access log</div>
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500"><tr><th>Provider</th><th>Created</th><th>Expires</th><th>Claims</th><th>Opened</th><th></th></tr></thead>
          <tbody className="divide-y">
            {links.map((l) => (
              <tr key={l.token} className={l.revoked ? "opacity-50" : ""}>
                <td className="py-1.5">{l.provider_name}</td>
                <td>{fmtDateTime(l.created_at)}</td>
                <td>{fmtDateTime(l.expires_at)}</td>
                <td>{l.claim_count}</td>
                <td>{l.opens.length ? <span title={l.opens.map((o: any) => fmtDateTime(o.opened_at)).join("\n")}>{l.opens.length}× · last {fmtDateTime(l.opens[0].opened_at)}</span> : <span className="text-slate-400">not yet</span>}
                  {l.notify_email && <span className="chip ml-1 bg-sky-100 text-sky-800">subscribed</span>}</td>
                <td className="text-right">
                  <a className="btn-ghost" href={`/p/${l.token}`} target="_blank">Open</a>
                  {!l.revoked ? <button className="btn-ghost text-rose-600" onClick={() => api.revoke(l.token).then(refreshLinks)}>Revoke</button> : <span className="text-xs">revoked</span>}
                </td>
              </tr>
            ))}
            {!links.length && <tr><td colSpan={6} className="py-3 text-slate-500">No links shared yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function parseWf(text: string) {
  const m = text.match(/\$([\d,.]+) is number (\d+) of (\d+)/);
  return m ? { billed: Number(m[1].replace(/,/g, "")), position: Number(m[2]), count: Number(m[3]) } : {};
}
