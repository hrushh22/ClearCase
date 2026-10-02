import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import ShareBuilder from "./pages/ShareBuilder";
import CaseXRay from "./pages/CaseXRay";
import ProviderPortal from "./pages/ProviderPortal";
import { SourceProvider } from "./components/SourceViewer";
import { api, authedUrl, fmtDateTime, session } from "./lib/api";

function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = (e: any) => {
    e.preventDefault(); setBusy(true); setErr(null);
    api.login(pw).then((r) => { session.set(r.token); onDone(); }).catch(() => setErr("Wrong password")).finally(() => setBusy(false));
  };
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-3 p-6">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 font-bold text-white">C</div>
          <div className="font-semibold">ClearCase</div>
        </div>
        <div className="text-sm text-slate-600">Attorney workspace. Enter the team password. (Provider links don't need it.)</div>
        <input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password"
          className="w-full rounded-lg border px-3 py-2" />
        {err && <div className="text-sm text-rose-700">{err}</div>}
        <button className="btn-primary w-full justify-center" disabled={busy || !pw}>{busy ? "Checking…" : "Open ClearCase"}</button>
      </form>
    </div>
  );
}

function Gate() {
  const [state, setState] = useState<"checking" | "login" | "ok">("checking");
  useEffect(() => {
    const onAuth = () => setState("login");
    window.addEventListener("clearcase:auth", onAuth);
    api.health().then((h) => setState(h.gate && !session.get() ? "login" : "ok")).catch(() => setState("ok"));
    return () => window.removeEventListener("clearcase:auth", onAuth);
  }, []);
  if (state === "checking") return <div className="p-8 text-center text-slate-500">Connecting to ClearCase…</div>;
  if (state === "login") return <Login onDone={() => setState("ok")} />;
  return <Attorney />;
}

function Attorney() {
  const [d, setD] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"brief" | "deep">("brief");
  const poll = useRef<any>(null);
  const markedFor = useRef<string | null>(null);

  const load = useCallback(() => api.digest().then((x) => { setD(x); setErr(null); }).catch((e) => setErr(e.message)), []);
  const refreshStatus = useCallback(() => api.status().then(setStatus), []);

  useEffect(() => { load(); refreshStatus(); }, [load, refreshStatus]);
  // record this visit a few seconds after the digest is on screen (powers "what changed since you last opened")
  useEffect(() => {
    if (!d || markedFor.current === d.content_hash) return;
    markedFor.current = d.content_hash;
    const t = setTimeout(() => api.seen(), 4000);
    return () => clearTimeout(t);
  }, [d]);

  useEffect(() => {
    if (status?.pipeline?.running) {
      poll.current = setTimeout(refreshStatus, 1500);
    } else if (status && poll.current) {
      poll.current = null;
      load();
    }
    return () => clearTimeout(poll.current);
  }, [status, load, refreshStatus]);

  const sync = (force = false) => api.sync(force).then(() => setTimeout(refreshStatus, 400));
  const ls = status?.last_sync;
  const running = status?.pipeline?.running;

  return (
    <SourceProvider>
      <div className="min-h-screen">
        <header className="sticky top-0 z-40 border-b bg-white/90 backdrop-blur">
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-4 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 font-bold text-white">C</div>
              <div className="font-semibold">ClearCase</div>
            </div>
            <nav className="flex gap-1">
              <NavLink to="/" end className={({ isActive }) => `btn ${isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>Case digest</NavLink>
              <NavLink to="/xray" className={({ isActive }) => `btn ${isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>Case X-Ray</NavLink>
              <NavLink to="/share" className={({ isActive }) => `btn ${isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>Share with providers</NavLink>
            </nav>
            <div className="flex rounded-lg bg-slate-100 p-0.5 text-sm">
              <button onClick={() => setMode("brief")} className={`rounded-md px-3 py-1 ${mode === "brief" ? "bg-white shadow-sm font-medium" : "text-slate-600"}`}>2-minute brief</button>
              <button onClick={() => setMode("deep")} className={`rounded-md px-3 py-1 ${mode === "deep" ? "bg-white shadow-sm font-medium" : "text-slate-600"}`}>Dig deep</button>
            </div>
            <div className="ml-auto flex items-center gap-3 text-xs text-slate-500">
              <div className="text-right leading-tight">
                <div>
                  {ls ? <>Last synced from Clio {fmtDateTime(ls.synced_at)}</> : "Not synced yet"}
                  {ls?.kind === "mirror" && <span className="chip ml-1 bg-amber-100 text-amber-800">offline mirror, not live Clio</span>}
                  {ls?.kind === "live" && <span className="chip ml-1 bg-emerald-100 text-emerald-800">live · read-only</span>}
                </div>
                {d && <div>Digest generated {fmtDateTime(d.created_at)} from {d.record_count} records · cached, no AI on open</div>}
              </div>
              <button className="btn-primary" disabled={running} onClick={() => sync(false)} title="Read Clio (GET only); rebuild only if something changed">
                {running ? "Syncing…" : "Sync from Clio"}
              </button>
              <button className="btn-ghost" disabled={running} onClick={() => sync(true)} title="Rebuild the digest even if Clio did not change">Rebuild</button>
            </div>
          </div>
          {running && (
            <div className="border-t bg-indigo-50 px-4 py-1.5 text-center text-xs text-indigo-800">
              <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-indigo-600" />{status.pipeline.step}
            </div>
          )}
          {status?.pipeline?.error && <div className="border-t bg-rose-50 px-4 py-1.5 text-center text-xs text-rose-800">{status.pipeline.error}</div>}
          {status && status.llm_providers.length === 0 && (
            <div className="border-t bg-amber-50 px-4 py-1.5 text-center text-xs text-amber-900">
              No LLM keys in .env: running in heuristic mode (rules instead of AI). Add GEMINI / MISTRAL / GROQ keys and press Rebuild.
            </div>
          )}
        </header>
        <main className="mx-auto max-w-[1400px] p-4">
          {err && !d && (
            <div className="card p-8 text-center">
              <div className="text-lg font-semibold">No digest yet</div>
              <div className="mt-1 text-slate-600">{err}</div>
              <button className="btn-primary mt-4" onClick={() => sync(false)} disabled={running}>Sync from Clio</button>
              {status?.clio && !status.clio.connected && status.clio.source === "live" && (
                <div className="mt-3 text-sm text-slate-600">
                  Clio is not connected. {status.clio.oauth_configured ? <a className="text-indigo-600 underline" href={authedUrl("/auth/clio/login")}>Connect Clio (read-only)</a>
                    : "Fill CLIO_CLIENT_ID and CLIO_CLIENT_SECRET (or CLIO_ACCESS_TOKEN) in .env."}
                </div>
              )}
            </div>
          )}
          {d && (
            <Routes>
              <Route path="/" element={<Dashboard d={d} mode={mode} />} />
              <Route path="/share" element={<ShareBuilder d={d} />} />
              <Route path="/xray" element={<CaseXRay d={d} />} />
            </Routes>
          )}
        </main>
      </div>
    </SourceProvider>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/p/:token" element={<ProviderPortal />} />
      <Route path="/*" element={<Gate />} />
    </Routes>
  );
}
