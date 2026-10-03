import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import ShareBuilder from "./pages/ShareBuilder";
import CaseXRay from "./pages/CaseXRay";
import ProviderPortal from "./pages/ProviderPortal";
import { SourceProvider } from "./components/SourceViewer";
import ChatWidget from "./components/ChatWidget";
import { ArrowRight, Info, LayoutDashboard, Lock, RefreshCw, RotateCcw, Scale, ScanSearch, Share2 } from "lucide-react";
import { api, authedUrl, fmtDateTime, session } from "./lib/api";

function Logo({ size = 34 }: { size?: number }) {
  return (
    <div className="grad-bg flex items-center justify-center rounded-xl text-white shadow-md shadow-rose-200" style={{ width: size, height: size }}>
      <Scale size={size * 0.55} strokeWidth={2.2} aria-hidden />
    </div>
  );
}

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
      <form onSubmit={submit} className="card fade-up w-full max-w-sm overflow-hidden p-0">
        <div className="grad-bg px-6 py-7 text-white">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/20 backdrop-blur"><Scale size={24} aria-hidden /></div>
            <div>
              <div className="text-xl font-bold tracking-tight">ClearCase</div>
              <div className="text-xs text-white/85">The case file, made clear</div>
            </div>
          </div>
        </div>
        <div className="space-y-3 p-6">
          <div className="text-sm text-slate-600">Attorney workspace. Enter the team password. Provider links don&apos;t need it.</div>
          <div className="relative">
            <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-rose-400" aria-hidden />
            <input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password"
              className="w-full rounded-xl border border-rose-100 py-2.5 pl-9 pr-3 outline-none transition focus:border-rose-300 focus:ring-4 focus:ring-rose-100" />
          </div>
          {err && <div className="text-sm text-red-700">{err}</div>}
          <button className="btn-primary w-full justify-center py-2.5" disabled={busy || !pw}>{busy ? "Checking…" : <>Open ClearCase <ArrowRight size={16} /></>}</button>
        </div>
      </form>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="space-y-4">
      <div className="skeleton h-44" />
      <div className="grid gap-4 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-28" />)}</div>
      <div className="grid gap-4 lg:grid-cols-3"><div className="skeleton h-64 lg:col-span-2" /><div className="skeleton h-64" /></div>
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
  if (state === "checking") return <div className="w-full px-3 sm:px-5 lg:px-8 2xl:px-12 py-6"><PageSkeleton /></div>;
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

  const navCls = ({ isActive }: { isActive: boolean }) =>
    `inline-flex shrink-0 items-center gap-2 rounded-xl px-2.5 py-2 text-sm font-medium transition md:px-3.5 ${isActive ? "bg-rose-50 text-rose-700 shadow-inner" : "text-slate-600 hover:bg-rose-50 hover:text-rose-700"}`;
  return (
    <SourceProvider>
      <div className="min-h-screen">
        <header className="sticky top-0 z-40 border-b border-rose-100 bg-white/80 backdrop-blur-xl">
          <div className="flex w-full items-center gap-2 px-3 sm:px-5 lg:px-8 2xl:px-12 py-2.5 sm:gap-3">
            <div className="flex shrink-0 items-center gap-2.5 sm:pr-2">
              <Logo />
              <div className="hidden leading-tight sm:block">
                <div className="grad-text text-lg font-extrabold tracking-tight">ClearCase</div>
                <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-slate-400">Case intelligence</div>
              </div>
            </div>
            <nav className="flex min-w-0 gap-1" aria-label="Main">
              <NavLink to="/" end className={navCls} title="Case digest"><LayoutDashboard size={16} aria-hidden /><span className="hidden md:inline">Case digest</span></NavLink>
              <NavLink to="/xray" className={navCls} title="Case X-Ray"><ScanSearch size={16} aria-hidden /><span className="hidden md:inline">Case X-Ray</span></NavLink>
              <NavLink to="/share" className={navCls} title="Share with providers"><Share2 size={16} aria-hidden /><span className="hidden md:inline">Share with providers</span></NavLink>
            </nav>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <div className="group relative hidden sm:block">
                <div className={`chip cursor-default gap-1.5 px-3 py-1.5 text-xs ${ls?.kind === "mirror" ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>
                  <span className={`h-2 w-2 rounded-full ${ls?.kind === "mirror" ? "bg-amber-500" : "animate-pulse bg-emerald-500"}`} />
                  <span className="hidden lg:inline"><span className="hidden lg:inline">{ls ? (ls.kind === "mirror" ? "Offline mirror" : "Live from Clio · read-only") : "Not synced yet"}</span><span className="lg:hidden">{ls?.kind === "mirror" ? "Mirror" : "Live"}</span></span><span className="lg:hidden">{ls?.kind === "mirror" ? "Mirror" : "Live"}</span>
                  <Info size={13} className="opacity-60" aria-hidden />
                </div>
                <div className="pointer-events-none absolute right-0 top-full z-50 mt-2 w-72 rounded-2xl border border-rose-100 bg-white p-3 text-xs text-slate-600 opacity-0 shadow-xl transition group-hover:opacity-100">
                  <div><b>Last synced:</b> {ls ? fmtDateTime(ls.synced_at) : "never"}</div>
                  {d && <div className="mt-1"><b>Digest:</b> generated {fmtDateTime(d.created_at)} from {d.record_count} records</div>}
                  <div className="mt-1 text-slate-500">Cached: opening a case runs no AI. ClearCase only reads Clio; it never writes.</div>
                </div>
              </div>
              <button className="btn-primary" disabled={running} onClick={() => sync(false)} title="Read Clio (GET only); rebuild only if something changed">
                <RefreshCw size={15} className={running ? "animate-spin" : ""} aria-hidden /><span className="hidden sm:inline">{running ? "Syncing…" : "Sync"}</span>
              </button>
              <button className="btn-ghost" disabled={running} onClick={() => sync(true)} title="Rebuild the digest even if Clio did not change (slow)">
                <RotateCcw size={15} aria-hidden /><span className="hidden xl:inline">Rebuild</span>
              </button>
            </div>
          </div>
          {running && (
            <div className="grad-soft border-t border-rose-100 px-4 py-1.5 text-center text-xs text-rose-800">
              <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-rose-500" />{status.pipeline.step}
            </div>
          )}
          {status?.pipeline?.error && <div className="border-t bg-red-50 px-4 py-1.5 text-center text-xs text-red-800">{status.pipeline.error}</div>}
          {status && status.llm_providers.length === 0 && (
            <div className="border-t bg-amber-50 px-4 py-1.5 text-center text-xs text-amber-900">
              No LLM keys in .env: running in heuristic mode (rules instead of AI). Add GEMINI / MISTRAL / GROQ keys and press Rebuild.
            </div>
          )}
        </header>
        <main className="w-full px-3 sm:px-5 lg:px-8 2xl:px-12 pb-24 pt-4 sm:pt-5">
          {!d && !err && <PageSkeleton />}
          {err && !d && (
            <div className="card p-8 text-center">
              <div className="text-lg font-semibold">No digest yet</div>
              <div className="mt-1 text-slate-600">{err}</div>
              <button className="btn-primary mt-4" onClick={() => sync(false)} disabled={running}>Sync from Clio</button>
              {status?.clio && !status.clio.connected && status.clio.source === "live" && (
                <div className="mt-3 text-sm text-slate-600">
                  Clio is not connected. {status.clio.oauth_configured ? <a className="text-rose-600 underline" href={authedUrl("/auth/clio/login")}>Connect Clio (read-only)</a>
                    : "Fill CLIO_CLIENT_ID and CLIO_CLIENT_SECRET (or CLIO_ACCESS_TOKEN) in .env."}
                </div>
              )}
            </div>
          )}
          {d && (
            <Routes>
              <Route path="/" element={<Dashboard d={d} mode={mode} setMode={setMode} />} />
              <Route path="/share" element={<ShareBuilder d={d} />} />
              <Route path="/xray" element={<CaseXRay d={d} />} />
            </Routes>
          )}
        </main>
        {d && <ChatWidget mode="attorney" />}
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
