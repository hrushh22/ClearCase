import { useCallback, useEffect, useMemo, useState } from "react";
import CaseConstellation from "../components/xray/CaseConstellation";
import EvidenceCoverage from "../components/xray/EvidenceCoverage";
import GapMap from "../components/xray/GapMap";
import InjuryMap from "../components/xray/InjuryMap";
import Issues from "../components/xray/Issues";
import StressTest from "../components/xray/StressTest";
import { api, fmtDate, fmtDateTime } from "../lib/api";

function Section({ title, sub, children, id }: any) {
  return (
    <section id={id} className="card p-5">
      <div className="mb-3">
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {sub && <div className="text-xs text-slate-500">{sub}</div>}
      </div>
      {children}
    </section>
  );
}

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
  const [spotlight, setSpotlight] = useState(false);
  const [openIssue, setOpenIssue] = useState<string | null>(null);

  const load = useCallback((as?: string | null) => api.xray(as || undefined).then((r) => { setX(r); setErr(null); }).catch((e) => setErr(e.message)), []);
  useEffect(() => { const t = setTimeout(() => load(asOf), 200); return () => clearTimeout(t); }, [asOf, d.content_hash]);

  const issuesById = useMemo(() => Object.fromEntries((x?.issues || []).map((i: any) => [i.id, i])), [x]);
  const today = new Date().toISOString().slice(0, 10);
  const start = x?.incident_date || d.snapshot.open_date || "2023-01-01";
  const goIssue = (id: string) => { setOpenIssue(null); setTimeout(() => setOpenIssue(id), 0);
    document.getElementById("xray-issues")?.scrollIntoView({ behavior: "smooth" }); };

  if (err) return <div className="card p-8 text-center text-slate-600">{err}</div>;
  if (!x) return <div className="card p-8 text-center text-slate-500">Loading Case X-Ray…</div>;
  const imp = x.impact || {};
  const c = x.counts;

  return (
    <div className="space-y-4">
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-end gap-6 bg-slate-900 p-6 text-white">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-300">Case X-Ray</div>
            <div className="mt-1 text-3xl font-bold tracking-tight">
              ClearCase found {x.total} item{x.total === 1 ? "" : "s"} worth reviewing
            </div>
            <div className="mt-1 text-sm text-slate-300">
              {asOf ? <b className="text-amber-300">{x.label}</b> : <>Case X-Ray generated {fmtDateTime(x.generated_at)} from {x.verified_fact_count} verified facts</>}
              {" "}· evidence consistency and completeness, not a prediction
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 text-center sm:grid-cols-4">
            {[["≠", "Contradictions", c.contradictions], ["?", "Evidence gaps", c.gaps], ["⧗", "Unresolved dependencies", c.dependencies],
              ["△", "Needs review", c.needs_review]].map(([g, l, n]) => (
              <div key={l as string} className="rounded-xl bg-white/10 px-4 py-2">
                <div className="text-2xl font-bold">{n as number}</div>
                <div className="text-[11px] text-slate-300"><span aria-hidden>{g}</span> {l}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t px-6 py-3 text-sm">
          {!asOf && imp.compared_to && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">New evidence impact:</span>
              {imp.resolved?.length > 0 && <span className="chip bg-emerald-100 text-emerald-800">✓ {imp.resolved.length} resolved</span>}
              {imp.supporting_facts_added > 0 && <span className="chip bg-sky-100 text-sky-800">+ {imp.supporting_facts_added} supporting facts</span>}
              {imp.new_contradictions > 0 && <span className="chip bg-rose-100 text-rose-800">⚠ {imp.new_contradictions} new inconsistenc{imp.new_contradictions === 1 ? "y" : "ies"}</span>}
              {imp.new_gaps > 0 && <span className="chip bg-amber-100 text-amber-800">? {imp.new_gaps} new open items</span>}
              {imp.reopened?.length > 0 && <span className="chip bg-rose-100 text-rose-800">↺ {imp.reopened.length} reopened</span>}
              {!imp.resolved?.length && !imp.supporting_facts_added && !imp.new_contradictions && !imp.new_gaps && <span className="text-slate-500">no change since the last build</span>}
            </div>
          )}
          {!asOf && !imp.compared_to && <span className="text-slate-500">First X-Ray of this file: issue history starts now.</span>}
          <div className="ml-auto flex min-w-[320px] flex-1 items-center gap-2">
            <span className="whitespace-nowrap text-xs font-semibold text-slate-600">Time travel</span>
            <input type="range" className="flex-1 accent-indigo-600" min={toDay(start)} max={toDay(today)} value={toDay(asOf || today)}
              onChange={(e) => { const v = fromDay(Number(e.target.value)); setAsOf(v >= today ? null : v); }} />
            <span className="w-24 text-xs tabular-nums">{asOf ? fmtDate(asOf) : "today"}</span>
            {asOf && <button className="chip bg-slate-100" onClick={() => setAsOf(null)}>reset</button>}
          </div>
        </div>
      </div>

      <Section title="Case Constellation" sub="The key propositions and open issues in this case, with the injuries and people involved. Click any card to see the evidence behind it.">
        <CaseConstellation x={x} focus={focus} onFocusIssue={goIssue} />
      </Section>

      <Section title="Evidence coverage" sub="Support state per key proposition, computed from countable evidence (verified sources, source types, contradictions, gaps). No percentages or outcome scores.">
        <EvidenceCoverage props={x.propositions} onFocus={(ids) => { setFocus(ids); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
      </Section>

      <Section id="xray-issues" title="Issues requiring review" sub="Contradictions, evidence gaps and unresolved dependencies. Every item opens its sources.">
        <div className="mb-4">
          <div className="card-h mb-2">Care chain and evidence gaps</div>
          <GapMap x={x} onOpenIssue={goIssue} />
        </div>
        <Issues x={x} spotlight={spotlight} setSpotlight={setSpotlight} onFocus={setFocus} reload={() => load(asOf)} openId={openIssue} />
      </Section>

      <Section title="Injury X-Ray" sub="Body regions from extracted injury and treatment facts only. Anything without a named body part stays unmapped.">
        <InjuryMap injury={x.injury} issuesById={issuesById} onOpenIssue={goIssue} />
      </Section>

      {!asOf && (
        <Section title="Stress Test My Case" sub="An adversarial review of evidence quality and completeness using only what is in the file.">
          <StressTest initial={x.stress} />
        </Section>
      )}

      <div className="px-1 text-xs text-slate-500">
        Case X-Ray evaluates consistency and evidence completeness within the available file. It does not determine legal truth,
        predict case outcomes, or replace attorney judgment.
      </div>
    </div>
  );
}
