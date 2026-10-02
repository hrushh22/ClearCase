import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import nacl from "tweetnacl";
import ProviderView, { type ProviderClaim } from "../components/ProviderView";
import { api } from "../lib/api";

const b64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

/** Verify each claim's Ed25519 signature in the browser against the firm's public key. */
function verifyClaim(payload: string, signature: string, publicKey: string): { ok: boolean; pkg: any } {
  try {
    const pkg = JSON.parse(payload);
    const ok = nacl.sign.detached.verify(new TextEncoder().encode(payload), b64(signature), b64(publicKey));
    const fresh = !pkg.expires_at || new Date(pkg.expires_at) > new Date();
    return { ok: ok && fresh, pkg };
  } catch {
    return { ok: false, pkg: { claim: "(unreadable)" } };
  }
}

export default function ProviderPortal() {
  const { token = "" } = useParams();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sub, setSub] = useState<string | null>(null);
  const [checked, setChecked] = useState<Date | null>(null);
  const openedAt = useRef<string>(new Date().toISOString());
  useEffect(() => {
    api.provider(token).then((d) => { setData(d); setChecked(new Date()); }).catch((e) => setErr(e.message));
    // live: check for case movement every 30 s (background checks are not logged as new opens)
    const t = setInterval(() => api.provider(token, true).then((d) => { setData(d); setChecked(new Date()); }).catch(() => {}), 30000);
    return () => clearInterval(t);
  }, [token]);

  if (err) return <Shell><div className="card p-8 text-center text-slate-600">This link was not found.</div></Shell>;
  if (!data) return <Shell><div className="p-8 text-center text-slate-500">Loading…</div></Shell>;
  if (data.error) return (
    <Shell firm={data.firm_name}>
      <div className="card p-8 text-center text-slate-600">
        This link {data.error === "revoked" ? "was withdrawn by the firm" : "has expired"}. Please contact {data.firm_name} for an updated link.
      </div>
    </Shell>
  );

  // the stage claim may have been re-issued on movement; keep the latest one of each kind
  const claims: ProviderClaim[] = data.claims.map((c: any) => {
    const v = verifyClaim(c.payload, c.signature, data.public_key);
    return { id: c.id, text: v.pkg.claim, category: c.category || "status", verified: v.ok ? "ok" : "bad", issued_at: v.pkg.issued_at,
      fresh: !!v.pkg.issued_at && v.pkg.issued_at > openedAt.current.slice(0, 19) };
  });
  const allOk = claims.every((c) => c.verified === "ok");
  return (
    <Shell firm={data.firm_name}>
      <div className="mb-2 flex items-center justify-end gap-2 text-xs text-slate-500">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500" aria-hidden />
        Live · last case update {new Date(data.updated_at).toLocaleString()} · checked {checked ? checked.toLocaleTimeString() : "…"}
      </div>
      <div className={`mb-4 rounded-xl p-3 text-sm ${allOk ? "bg-emerald-50 text-emerald-900" : "bg-rose-50 text-rose-900"}`}>
        {allOk ? `Every item below was checked in your browser: it came from ${data.firm_name} and has not been changed.`
          : "Some items could not be verified. Treat them with caution and contact the firm."}
      </div>
      <ProviderView firm={data.firm_name} provider={data.provider_name} claims={claims} waterfall={data.waterfall} events={data.events}
        subscribed={sub || (data.notify_email ? `Updates go to ${data.notify_email}` : null)}
        onSubscribe={(email) => api.subscribe(token, email).then((r) => setSub(r.ok ? `Subscribed ${email} (${r.email_mode}).` : "Could not subscribe."))} />
      <div className="mt-6 text-center text-xs text-slate-400">Shared on purpose, item by item. You are not seeing the firm's file. Link expires {new Date(data.expires_at).toLocaleDateString()}.</div>
    </Shell>
  );
}

function Shell({ children, firm }: { children: any; firm?: string }) {
  return (
    <div className="min-h-screen">
      <div className="border-b bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <div className="font-semibold">{firm || "Case status"}</div>
          <div className="text-xs text-slate-500">Provider case status · powered by ClearCase</div>
        </div>
      </div>
      <div className="mx-auto max-w-3xl p-4">{children}</div>
    </div>
  );
}
