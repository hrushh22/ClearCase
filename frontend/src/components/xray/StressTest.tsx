import { useState } from "react";
import { Cite } from "../SourceViewer";
import { api, fmtDateTime } from "../../lib/api";

function Item({ it, tone }: { it: any; tone: string }) {
  const [show, setShow] = useState(false);
  return (
    <li className={`rounded-lg border-l-4 bg-white p-2 ${tone}`}>
      {it.proposition && <div className="text-[11px] font-semibold uppercase text-slate-500">{it.proposition}</div>}
      <div className="text-sm">{it.text || it.title}</div>
      <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
        {it.status === "needs_review" ? <span className="chip bg-amber-100 text-amber-800">△ Needs review</span>
          : it.status ? <span className="chip bg-emerald-50 text-emerald-700">✓ Checked against sources</span> : null}
        {it.judge && <span className="text-slate-500">Judge: {it.judge}</span>}
        {it.evidence?.length > 0 && <button className="btn-ghost px-1 py-0 text-rose-700" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"} evidence ({it.evidence.length})</button>}
      </div>
      {show && <div className="mt-1 flex flex-wrap gap-1">{it.evidence.map((e: any, k: number) => <Cite key={k} src={e} label={(e.text || e.quote || "source").slice(0, 40)} />)}</div>}
    </li>
  );
}

export default function StressTest({ initial }: { initial: any }) {
  const [res, setRes] = useState<any>(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = (force = false) => { setBusy(true); setErr(null); api.stressTest(force).then(setRes).catch((e) => setErr(e.message)).finally(() => setBusy(false)); };
  const sections: [string, string, any[], string][] = res ? [
    ["Strongly Supported", "s", res.strong, "border-emerald-400"],
    ["Potential Vulnerabilities", "v", res.vulnerabilities, "border-red-400"],
    ["Evidence Gaps", "g", res.gaps, "border-amber-400"],
    ["Suggested Follow-Ups", "f", res.follow_ups, "border-rose-400"],
  ] : [];
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" disabled={busy} onClick={() => run(false)}>{busy ? "Reviewing the file…" : res ? "Re-run Stress Test" : "Stress Test My Case"}</button>
        {res && <button className="btn-ghost" disabled={busy} onClick={() => run(true)}>Force fresh run</button>}
        <span className="text-xs text-slate-500">
          Three roles: supporting analyst · adversarial reviewer · evidence judge.{" "}
          {res && `${res.method === "llm" ? "AI review" : "Rule-based review (no LLM)"} · ${fmtDateTime(res.generated_at)}${res.cached ? " · cached" : ""}${res.rejected ? ` · ${res.rejected} unsupported items rejected` : ""}`}
        </span>
      </div>
      {err && <div className="mt-2 text-sm text-red-700">{err}</div>}
      {res && (
        <>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {sections.map(([title, k, items, tone]) => (
              <div key={k}>
                <div className="card-h mb-1">{title} · {items.length}</div>
                {items.length === 0 ? <div className="text-sm text-slate-500">None found in the file.</div> : (
                  <ul className="max-h-[420px] space-y-2 overflow-auto pr-1">{items.map((it: any, n: number) => <Item key={n} it={it} tone={tone} />)}</ul>
                )}
              </div>
            ))}
          </div>
          <div className="mt-3 text-xs text-slate-500">{res.disclaimer}</div>
        </>
      )}
    </div>
  );
}
