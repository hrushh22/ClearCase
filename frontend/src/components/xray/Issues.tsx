import { useEffect, useRef, useState } from "react";
import { Cite, useSource } from "../SourceViewer";
import { api, fmtDate, fmtDateTime } from "../../lib/api";

const TYPE_LABEL: Record<string, { label: string; glyph: string; cls: string }> = {
  contradiction: { label: "Contradiction", glyph: "≠", cls: "bg-red-100 text-red-800" },
  amount_mismatch: { label: "Amount mismatch", glyph: "$≠", cls: "bg-red-100 text-red-800" },
  missing_evidence: { label: "Evidence gap", glyph: "?", cls: "bg-amber-100 text-amber-800" },
  timeline_gap: { label: "Timeline", glyph: "⏱", cls: "bg-amber-100 text-amber-800" },
  dependency: { label: "Waiting on", glyph: "⧗", cls: "bg-sky-100 text-sky-800" },
  unsupported_claim: { label: "Unsupported", glyph: "!", cls: "bg-slate-200 text-slate-700" },
};
const SEV: Record<string, string> = { high: "High", medium: "Medium", low: "Low" };

export function SplitView({ issue }: { issue: any }) {
  const open = useSource();
  const side = (s: any, which: string) => s ? (
    <div className="flex-1 rounded-lg border bg-white p-3">
      <div className="text-[11px] font-semibold uppercase text-slate-500">{which} · {s.source_type}{s.page ? ` p.${s.page}` : ""} · {fmtDate(s.date)}</div>
      <div className="mt-1 text-sm">{s.text}</div>
      {s.quote && s.quote !== s.text && <div className="mt-1 text-xs italic text-slate-500">“{s.quote}”</div>}
      <button className="btn-ghost mt-2 px-0 text-rose-700" onClick={() => open(s)}>Open {which.toLowerCase()} source →</button>
    </div>
  ) : (
    <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed p-3 text-xs text-slate-500">
      The file states the inconsistency itself; see related evidence below.
    </div>
  );
  return (
    <div>
      <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-center">
        {side(issue.left, "Left")}
        <div className="flex shrink-0 flex-col items-center px-2 text-center">
          <span className="text-2xl text-red-600" aria-hidden>≠</span>
          <span className="text-xs font-semibold text-red-700">{issue.label}</span>
        </div>
        {side(issue.right, "Right")}
      </div>
      <div className="mt-2 text-xs text-slate-500">ClearCase does not decide which source is correct.</div>
    </div>
  );
}

function Resolve({ issue, onDone }: { issue: any; onDone: () => void }) {
  const [draft, setDraft] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const act = (t: string) => { setBusy(true); api.xrayAction(issue.id, t).then((r) => { if (r.status === "draft") setDraft(r); onDone(); }).finally(() => setBusy(false)); };
  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">Resolve this {issue.issue_type.includes("contradiction") || issue.issue_type === "amount_mismatch" ? "issue" : "gap"}</div>
      <div className="mt-2 flex flex-wrap gap-1">
        <button disabled={busy} className="btn-ghost border bg-white" onClick={() => act("draft_records_request")}>Draft records request</button>
        <button disabled={busy} className="btn-ghost border bg-white" onClick={() => act("draft_provider_followup")}>Draft follow-up</button>
        <button disabled={busy} className="btn-ghost border bg-white" onClick={() => act("internal_followup")}>Internal follow-up</button>
        <button disabled={busy} className="btn-ghost border bg-white" onClick={() => act("mark_reviewed")}>Mark reviewed</button>
        <button disabled={busy} className="btn-ghost border bg-white" onClick={() => act("snooze")}>Snooze</button>
        <button disabled={busy} className="btn-ghost border bg-white" onClick={() => act("mark_explained")}>Explained / resolved</button>
      </div>
      <div className="mt-1 text-[11px] text-slate-500">Saved in ClearCase only. Nothing is sent and nothing is written to Clio.</div>
      {draft && (
        <div className="mt-2">
          <textarea readOnly value={draft.content} className="h-44 w-full rounded border bg-white p-2 font-mono text-xs" />
          <button className="btn-ghost text-rose-700" onClick={() => navigator.clipboard?.writeText(draft.content)}>Copy draft</button>
        </div>
      )}
      {issue.actions?.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[11px] text-slate-500">
          {issue.actions.slice(-4).map((a: any) => <li key={a.id}>{fmtDateTime(a.created_at)} · {a.type.replace(/_/g, " ")}</li>)}
        </ul>
      )}
    </div>
  );
}

export default function Issues({ x, spotlight, setSpotlight, onFocus, reload, openId }: {
  x: any; spotlight: boolean; setSpotlight: (b: boolean) => void; onFocus: (ids: string[]) => void; reload: () => void; openId: string | null;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [idx, setIdx] = useState(0);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  const spot = (x.spotlight || []).map((s: any) => s.issue_id);
  const spotWhy = Object.fromEntries((x.spotlight || []).map((s: any) => [s.issue_id, s]));

  useEffect(() => { if (openId) { setOpen(openId); refs.current[openId]?.scrollIntoView({ behavior: "smooth", block: "center" }); } }, [openId]);
  useEffect(() => {
    if (!spotlight || !spot.length) return;
    const id = spot[idx % spot.length];
    setOpen(id);
    refs.current[id]?.scrollIntoView({ behavior: "smooth", block: "center" });
    const i = x.issues.find((i: any) => i.id === id);
    if (i) onFocus([`issue_${id}`, ...(i.related_fact_ids || []).map((f: string) => `fact_${f}`)]);
  }, [spotlight, idx]);

  const shown = x.issues.filter((i: any) => filter === "all" || (filter === "open" ? i.review?.status === "open" : i.issue_type === filter ||
    (filter === "contradiction" && i.issue_type === "amount_mismatch")));
  if (!x.issues.length) return <div className="text-sm text-slate-500">No verified contradictions were detected. ClearCase did not identify an obvious evidence gap.</div>;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-1">
        {[["all", "All"], ["open", "Open"], ["contradiction", "Contradictions"], ["missing_evidence", "Gaps"], ["dependency", "Waiting on"], ["timeline_gap", "Timeline"]].map(([k, l]) => (
          <button key={k} onClick={() => setFilter(k)} className={`chip ${filter === k ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>{l}</button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => { setSpotlight(!spotlight); setIdx(0); }} className={`btn ${spotlight ? "bg-amber-500 text-white" : "border bg-white text-slate-700"}`}>
            ✦ AI Spotlight {spotlight ? "on" : ""}
          </button>
          {spotlight && <button className="btn-ghost border" onClick={() => setIdx(idx + 1)}>Next ({(idx % spot.length) + 1}/{spot.length}) →</button>}
        </div>
      </div>
      <div className="space-y-2">
        {shown.map((i: any) => {
          const t = TYPE_LABEL[i.issue_type] || TYPE_LABEL.unsupported_claim;
          const isOpen = open === i.id;
          const lit = spotlight && spot.includes(i.id);
          const life = x.lifecycle?.[i.id];
          return (
            <div key={i.id} ref={(el) => { refs.current[i.id] = el; }}
              className={`card-lift rounded-2xl border border-rose-100 bg-white transition ${spotlight && !lit ? "opacity-30" : ""} ${lit && spot[idx % spot.length] === i.id ? "ring-2 ring-amber-400" : ""}`}>
              <button className="flex w-full items-start gap-3 p-3 text-left" onClick={() => { setOpen(isOpen ? null : i.id);
                onFocus([`issue_${i.id}`, ...(i.related_fact_ids || []).map((f: string) => `fact_${f}`)]); }}>
                <span className={`chip shrink-0 ${t.cls}`}><span aria-hidden>{t.glyph}</span>{t.label}</span>
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{i.title}</div>
                  <div className="text-xs text-slate-500">
                    {SEV[i.severity]} priority · {i.evidence_for.length} source{i.evidence_for.length === 1 ? "" : "s"}
                    {i.method === "llm" && " · paired by AI"}
                    {life?.first_detected_at && ` · first detected ${fmtDate(life.first_detected_at)}`}
                    {life?.reopened_at && " · reopened"}
                    {(x.impact?.new || []).includes(i.id) && <span className="ml-1 rounded bg-sky-600 px-1 text-[10px] text-white">NEW</span>}
                  </div>
                  {lit && <div className="mt-1 text-xs text-amber-800">✦ {spotWhy[i.id]?.why}</div>}
                </div>
                {i.verify_status === "needs_review" ? <span className="chip shrink-0 bg-amber-100 text-amber-800">△ Needs review</span>
                  : <span className="chip shrink-0 bg-emerald-100 text-emerald-800">✓ Verified source</span>}
                {i.review?.status !== "open" && <span className="chip shrink-0 bg-slate-200 text-slate-700">{i.review.status}</span>}
              </button>
              {isOpen && (
                <div className="border-t px-3 pb-3 pt-2 text-sm">
                  <p className="text-slate-700">{i.explanation}</p>
                  {(i.issue_type === "contradiction" || i.issue_type === "amount_mismatch" || i.kind === "sequence") && <div className="mt-2"><SplitView issue={i} /></div>}
                  <div className="mt-2 text-xs font-semibold uppercase text-slate-500">Related evidence</div>
                  <ul className="mt-1 space-y-1">
                    {i.evidence_for.map((e: any, k: number) => (
                      <li key={k} className="flex items-start gap-2 text-sm"><span className="flex-1">{e.text || e.quote}</span><Cite src={e} /></li>
                    ))}
                  </ul>
                  <div className="mt-2 text-sm"><span className="font-semibold">Suggested follow-up: </span>{i.suggested_action}</div>
                  {spotWhy[i.id] && (
                    <div className="mt-1 text-[11px] text-slate-500" title={JSON.stringify(spotWhy[i.id].components)}>
                      Spotlight rank from: {Object.entries(spotWhy[i.id].components).filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(" · ")}
                    </div>
                  )}
                  <Resolve issue={i} onDone={reload} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
