import { useState } from "react";
import { Cite } from "../SourceViewer";
import { fmtDate, money } from "../../lib/api";
import { STATE } from "./EvidenceCoverage";

// hotspot positions on a 200x420 front-view figure; left/right are the patient's (viewer's right = patient's left)
const SPOTS: Record<string, { x: number; y: number; r: number; mirror?: boolean }> = {
  head: { x: 100, y: 38, r: 22 },
  neck: { x: 100, y: 78, r: 11 },
  shoulder: { x: 60, y: 100, r: 15, mirror: true },
  arm: { x: 40, y: 170, r: 14, mirror: true },
  upper_back: { x: 100, y: 125, r: 15 },
  lower_back: { x: 100, y: 190, r: 16 },
  hip: { x: 76, y: 225, r: 13, mirror: true },
  knee: { x: 80, y: 305, r: 13, mirror: true },
  leg_foot: { x: 82, y: 385, r: 13, mirror: true },
};

function Figure({ regions, sel, setSel }: any) {
  const by = Object.fromEntries(regions.map((r: any) => [r.key, r]));
  const dots: any[] = [];
  Object.entries(SPOTS).forEach(([key, s]) => {
    const r = by[key];
    if (!r) return;
    const sides: string[] = r.sides || [];
    const xs = s.mirror
      ? (sides.includes("bilateral") || (sides.includes("left") && sides.includes("right")) ? [s.x, 200 - s.x]
        : sides.includes("left") ? [200 - s.x] : sides.includes("right") ? [s.x] : [s.x, 200 - s.x])
      : [s.x];
    xs.forEach((x, k) => dots.push({ key: `${key}${k}`, region: key, x, y: s.y, r: s.r, state: r.state, faint: s.mirror && !sides.length }));
  });
  return (
    <svg viewBox="0 0 200 420" className="h-[420px] w-[200px]" role="img" aria-label="Body map of documented injuries">
      <g fill="#f1f5f9" stroke="#cbd5e1" strokeWidth="2">
        <circle cx="100" cy="38" r="24" />
        <rect x="90" y="60" width="20" height="18" rx="6" />
        <path d="M58 88 Q100 76 142 88 L150 210 Q100 228 50 210 Z" />
        <path d="M58 92 L30 200 L42 204 L66 120 Z" /><path d="M142 92 L170 200 L158 204 L134 120 Z" />
        <path d="M60 212 L92 214 L90 400 L70 400 Z" /><path d="M140 212 L108 214 L110 400 L130 400 Z" />
      </g>
      <text x="22" y="16" fontSize="9" fill="#94a3b8">R</text><text x="172" y="16" fontSize="9" fill="#94a3b8">L</text>
      {dots.map((d) => (
        <g key={d.key} onClick={() => setSel(d.region)} className="cursor-pointer" role="button" aria-label={`${d.region} ${d.state}`}>
          <circle cx={d.x} cy={d.y} r={d.r} fill={d.state === "conflicting" ? "#fda4af" : d.state === "incomplete" ? "#fde68a" : "#fca5a5"}
            fillOpacity={d.faint ? 0.35 : 0.75} stroke={sel === d.region ? "#4f46e5" : "#e11d48"} strokeWidth={sel === d.region ? 3 : 1.5}
            strokeDasharray={d.state === "limited" || d.state === "incomplete" ? "3 2" : undefined} />
          <text x={d.x} y={d.y + 3} textAnchor="middle" fontSize="9" fill="#7f1d1d">{STATE[d.state]?.glyph}</text>
        </g>
      ))}
    </svg>
  );
}

export default function InjuryMap({ injury, issuesById, onOpenIssue }: { injury: any; issuesById: Record<string, any>; onOpenIssue: (id: string) => void }) {
  const regions = injury.regions || [];
  const [sel, setSel] = useState<string | null>(regions[0]?.key || null);
  const r = regions.find((x: any) => x.key === sel);
  if (!regions.length) return <div className="text-sm text-slate-500">No injury location could be mapped confidently.</div>;
  return (
    <div className="grid gap-4 md:grid-cols-[220px_1fr]">
      <div>
        <Figure regions={regions} sel={sel} setSel={setSel} />
        <div className="mt-1 text-[11px] text-slate-500">Placed only where the text names a body part. Faint = side not stated.</div>
      </div>
      <div>
        <div className="mb-2 flex flex-wrap gap-1">
          {regions.map((x: any) => (
            <button key={x.key} onClick={() => setSel(x.key)} className={`chip ${sel === x.key ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"}`}>
              {x.label}{x.sides.length ? ` (${x.sides.join("/")})` : ""} · {x.source_count}
            </button>
          ))}
          {injury.unmapped?.length > 0 && <span className="chip bg-slate-100 text-slate-500">Other / unmapped · {injury.unmapped.length}</span>}
        </div>
        {r && (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold">{r.label}</span>
              {r.sides.length > 0 && <span className="chip bg-slate-100">{r.sides.join(" / ")}</span>}
              <span className={`chip ${STATE[r.state].cls}`}>{STATE[r.state].glyph} {r.components.rule.split(".")[0]}</span>
            </div>
            <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
              <div><div className="card-h">First documented</div>{fmtDate(r.first_date)}</div>
              <div><div className="card-h">Supporting sources</div>{r.source_count}</div>
              <div><div className="card-h">Known billed</div>{r.known_billed_total ? money(r.known_billed_total) : "—"}</div>
              <div><div className="card-h">Issues</div>{r.contradictions.length} contradictions · {r.gaps.length} gaps</div>
            </div>
            {[["Injury / diagnosis", r.injuries], ["Imaging and tests", r.imaging], ["Treatment", r.treatment]].map(([t, list]: any) => list.length > 0 && (
              <div key={t}>
                <div className="card-h">{t}</div>
                <ul className="mt-1 space-y-1">
                  {list.slice(0, 6).map((e: any, k: number) => <li key={k} className="flex items-start gap-2"><span className="flex-1">{e.text}</span><Cite src={e} /></li>)}
                </ul>
              </div>
            ))}
            {r.providers.length > 0 && <div><div className="card-h">Providers named</div>{r.providers.join(" · ")}</div>}
            {r.related_bills.length > 0 && <div className="text-xs text-slate-500">{r.related_bills.map((b: any) => `${b.name} ${money(b.amount)}`).join(" · ")}. {r.billed_note}</div>}
            {[...r.contradictions, ...r.gaps].map((id: string) => issuesById[id] && (
              <button key={id} className="chip bg-amber-100 text-amber-800" onClick={() => onOpenIssue(id)}>⚠ {issuesById[id].title.slice(0, 60)}</button>
            ))}
          </div>
        )}
        {sel === null && injury.unmapped?.length > 0 && (
          <ul className="space-y-1 text-sm">{injury.unmapped.map((e: any, k: number) => <li key={k} className="flex gap-2"><span className="flex-1">{e.text}</span><Cite src={e} /></li>)}</ul>
        )}
      </div>
    </div>
  );
}
