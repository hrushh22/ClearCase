import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, CircleSlash, FlaskConical, GitFork, History, Hourglass, ListChecks, ScanSearch, SearchX, ShieldCheck, TriangleAlert } from "lucide-react";
import CaseConstellation from "../components/xray/CaseConstellation";
import EvidenceCoverage from "../components/xray/EvidenceCoverage";
import GapMap from "../components/xray/GapMap";
import InjuryMap from "../components/xray/InjuryMap";
import Issues from "../components/xray/Issues";
import StressTest from "../components/xray/StressTest";
import { SectionHeader } from "../components/ui";
import { api, fmtDate, fmtDateTime } from "../lib/api";

type Tab = "map" | "issues" | "body" | "stress" | "coverage";

const toDay = (s: string) => Math.floor(new Date(s + "T12:00:00").getTime() / 86400000);
const fromDay = (n: number) => new Date(n * 86400000).toISOString().slice(0, 10);

export default function CaseXRay({ d }: { d: any }) {
  const [x, setX] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string | null>(null);
  // deep link: /xray?focus=<proposition id | issue_<id>> opens that evidence view directly
  const [focus, setFocus] = useState<string[] | null>(() => {
    const q = window.location.hash.split("?")[1] || window.location.search.slice(1);  // hash routes carry their own query
    const f = new URLSearchParams(q).get("focus");
    return f ? [f] : null;
  });
  const [tab, setTab] = useState<Tab>("map");
  const [spotlight, setSpotlight] = useState(false);
  const [openIssue, setOpenIssue] = useState<string | null>(null);

  const load = useCallback((as?: string | null) => api.xray(as || undefined).then((r) => { setX(r); setErr(null); }).catch((e) => setErr(e.message)), []);
  useEffect(() => { const t = setTimeout(() => load(asOf), 200); return () => clearTimeout(t); }, [asOf, d.content_hash]);
  useEffect(() => { if (asOf && tab === "stress") setTab("map"); }, [asOf]);

  const issuesById = useMemo(() => Object.fromEntries((x?.issues || []).map((i: any) => [i.id, i])), [x]);
  const today = new Date().toISOString().slice(0, 10);
  const start = x?.incident_date || d.snapshot.open_date || "2023-01-01";
  const goIssue = (id: string) => { setTab("issues"); setOpenIssue(null); setTimeout(() => setOpenIssue(id), 50); };
  const goMap = (ids: string[]) => { setFocus(ids); setTab("map"); };

  if (err) return <div className="card p-8 text-center text-slate-600">{err}</div>;
  if (!x) return (
    <div className="space-y-4"><div className="skeleton h-48" /><div className="skeleton h-12 w-96" /><div className="skeleton h-[480px]" /></div>
  );
  const imp = x.impact || {};
  const c = x.counts;
  const tabs: { id: Tab; label: string; icon: any; badge?: number; hide?: boolean }[] = [
    { id: "map", label: "Map", icon: GitFork },
    { id: "issues", label: "Issues", icon: ListChecks, badge: x.total },
    { id: "body", label: "Body", icon: Activity, badge: x.injury?.regions?.length },
    { id: "stress", label: "Stress test", icon: FlaskConical, hide: !!asOf },
    { id: "coverage", label: "Coverage", icon: ShieldCheck },
  ];

  return (
    <div className="space-y-5">
      <section className="card fade-up overflow-hidden p-0">
        <div className="grad-bg relative px-4 py-5 text-white sm:px-6 sm:py-6">
          <div className="pointer-events-none absolute -right-20 -top-20 h-72 w-72 rounded-full bg-white/10 blur-2xl" />
          <div className="relative flex flex-wrap items-end gap-6">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-white/85"><ScanSearch size={14} />Case X-Ray</div>
              <div className="mt-1 text-2xl font-extrabold tracking-tight drop-shadow-sm sm:text-3xl">
                ClearCase found {x.total} item{x.total === 1 ? "" : "s"} worth reviewing
              </div>
              <div className="mt-1 text-sm text-white/90">
                {asOf ? <b className="rounded-md bg-white/20 px-1.5">{x.label}</b> : <>Generated {fmtDateTime(x.generated_at)} from {x.verified_fact_count} verified facts</>}
                {" "}· evidence consistency and completeness, not a prediction
              </div>
            </div>
            <div className="stagger grid w-full grid-cols-2 gap-2.5 sm:w-auto sm:grid-cols-4">
              {[[CircleSlash, "Contradictions", c.contradictions], [SearchX, "Evidence gaps", c.gaps], [Hourglass, "Waiting on others", c.dependencies],
                [TriangleAlert, "Needs review", c.needs_review]].map(([Icon, l, n]: any) => (
                <div key={l} className="rounded-2xl sm:min-w-[118px] bg-white/95 px-4 py-2.5 text-slate-900 shadow-sm transition hover:-translate-y-0.5">
                  <div className="flex items-center justify-between"><span className="text-2xl font-extrabold">{n}</span><Icon size={17} className="text-rose-500" /></div>
                  <div className="text-[11px] font-medium text-slate-500">{l}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm sm:px-6">
          {!asOf && imp.compared_to && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-700">New evidence impact:</span>
              {imp.resolved?.length > 0 && <span className="chip bg-emerald-100 text-emerald-800">✓ {imp.resolved.length} resolved</span>}
              {imp.supporting_facts_added > 0 && <span className="chip bg-sky-100 text-sky-800">+ {imp.supporting_facts_added} supporting facts</span>}
              {imp.new_contradictions > 0 && <span className="chip bg-red-100 text-red-800">⚠ {imp.new_contradictions} new inconsistenc{imp.new_contradictions === 1 ? "y" : "ies"}</span>}
              {imp.new_gaps > 0 && <span className="chip bg-amber-100 text-amber-800">? {imp.new_gaps} new open items</span>}
              {imp.reopened?.length > 0 && <span className="chip bg-red-100 text-red-800">↺ {imp.reopened.length} reopened</span>}
              {!imp.resolved?.length && !imp.supporting_facts_added && !imp.new_contradictions && !imp.new_gaps && <span className="text-slate-500">no change since the last build</span>}
            </div>
          )}
          {!asOf && !imp.compared_to && <span className="text-slate-500">First X-Ray of this file: issue history starts now.</span>}
          <div className="flex w-full items-center gap-2 rounded-xl bg-rose-50/70 px-3 py-1.5 md:ml-auto md:w-auto md:min-w-[320px] md:flex-1">
            <History size={15} className="text-rose-500" aria-hidden />
            <span className="whitespace-nowrap text-xs font-semibold text-slate-600">Time travel</span>
            <input type="range" className="flex-1 accent-rose-500" min={toDay(start)} max={toDay(today)} value={toDay(asOf || today)}
              onChange={(e) => { const v = fromDay(Number(e.target.value)); setAsOf(v >= today ? null : v); }} aria-label="Show the file as of a date" />
            <span className="w-24 text-xs font-medium tabular-nums text-rose-700">{asOf ? fmtDate(asOf) : "today"}</span>
            {asOf && <button className="chip bg-white text-rose-700" onClick={() => setAsOf(null)}>reset</button>}
          </div>
        </div>
      </section>

      <div className="tabs" role="tablist" aria-label="Case X-Ray sections">
        {tabs.filter((t) => !t.hide).map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className="tab" onClick={() => setTab(t.id)}>
            <t.icon size={16} aria-hidden />{t.label}
            {!!t.badge && <span className={`rounded-full px-1.5 text-[11px] font-semibold ${tab === t.id ? "bg-white/25 text-white" : "bg-rose-100 text-rose-700"}`}>{t.badge}</span>}
          </button>
        ))}
      </div>

      <div key={tab} className="fade-up" role="tabpanel">
        {tab === "map" && (
          <section className="card p-5">
            <SectionHeader icon={GitFork} title="Case Constellation" note="The key propositions and open issues. Click any card to see the evidence behind it." />
            <CaseConstellation x={x} focus={focus} onFocusIssue={goIssue} />
          </section>
        )}
        {tab === "issues" && (
          <section className="card p-5">
            <SectionHeader icon={ListChecks} title="Issues requiring review" note="Contradictions, evidence gaps and unresolved dependencies. Every item opens its sources." />
            <div className="mb-5 rounded-2xl border border-rose-100 bg-gradient-to-br from-rose-50/70 to-white p-4">
              <div className="card-h mb-2">Care chain and evidence gaps</div>
              <GapMap x={x} onOpenIssue={goIssue} />
            </div>
            <Issues x={x} spotlight={spotlight} setSpotlight={setSpotlight} onFocus={setFocus} reload={() => load(asOf)} openId={openIssue} />
          </section>
        )}
        {tab === "body" && (
          <section className="card p-5">
            <SectionHeader icon={Activity} title="Injury X-Ray" note="Body regions from injury and treatment facts only. Anything without a named body part stays unmapped." />
            <InjuryMap injury={x.injury} issuesById={issuesById} onOpenIssue={goIssue} />
          </section>
        )}
        {tab === "stress" && !asOf && (
          <section className="card p-5">
            <SectionHeader icon={FlaskConical} title="Stress Test My Case" note="An adversarial review of evidence quality and completeness, using only what is in the file." />
            <StressTest initial={x.stress} />
          </section>
        )}
        {tab === "coverage" && (
          <section className="card p-5">
            <SectionHeader icon={ShieldCheck} title="Evidence coverage" note="Support per key proposition from countable evidence. No percentages or outcome scores. Click one to see it on the map." />
            <EvidenceCoverage props={x.propositions} onFocus={goMap} />
          </section>
        )}
      </div>

      <div className="px-1 text-xs text-slate-500">
        Case X-Ray evaluates consistency and evidence completeness within the available file. It does not determine legal truth,
        predict case outcomes, or replace attorney judgment.
      </div>
    </div>
  );
}
