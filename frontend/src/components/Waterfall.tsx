import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from "recharts";
import { Cite } from "./SourceViewer";
import { api, money } from "../lib/api";

type LienRow = { name: string; amount: number; reduction: number; include: boolean; kind: string };

const STATUS = {
  full: { label: "fully covered", cls: "bg-emerald-100 text-emerald-800", color: "#10b981" },
  partial: { label: "partly covered", cls: "bg-amber-100 text-amber-800", color: "#f59e0b" },
  none: { label: "not covered", cls: "bg-rose-100 text-rose-800", color: "#f43f5e" },
} as const;

export default function Waterfall({ d }: { d: any }) {
  const wf = d.waterfall;
  const [gross, setGross] = useState<number>(wf.suggested_gross);
  const [fee, setFee] = useState<number>(wf.fee_pct);
  const [liens, setLiens] = useState<LienRow[]>([]);
  const [res, setRes] = useState<any>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const timer = useRef<any>(null);
  const sources = useMemo(() => Object.fromEntries(wf.liens.map((l: any) => [l.name, l.sources])), [wf]);

  const load = () =>
    api.waterfallSettings().then((s) => { setGross(s.gross); setFee(s.fee_pct); setLiens(s.liens); });
  useEffect(() => { load(); }, [d.content_hash]);

  useEffect(() => {
    if (!liens.length && wf.liens.length) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.waterfall({ gross, fee_pct: fee, liens }).then(setRes);
    }, 60);
  }, [gross, fee, liens]);

  const chart = useMemo(() => {
    if (!res) return [];
    let running = 0;
    return res.steps.map((s: any) => {
      if (s.kind === "gross") { running = s.value; return { ...s, base: 0, bar: s.value }; }
      if (s.kind === "net") return { ...s, base: Math.min(0, s.value), bar: Math.abs(s.value) };
      const next = running + s.value;
      const row = { ...s, base: Math.min(running, next), bar: Math.abs(s.value) };
      running = next;
      return row;
    });
  }, [res]);

  const setLien = (i: number, patch: Partial<LienRow>) => setLiens(liens.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= liens.length) return;
    const next = [...liens];
    [next[i], next[j]] = [next[j], next[i]];
    setLiens(next);
  };
  const save = () => api.waterfall({ gross, fee_pct: fee, liens, save: true }).then(() => { setSaved("Scenario saved; provider shares use it."); setTimeout(() => setSaved(null), 3000); });
  const reset = () => api.waterfallReset().then(load);
  const cov = d.kpis.coverage.value;
  const cv = d.kpis.case_value.value;
  const byName = Object.fromEntries((res?.liens || []).map((r: any) => [r.name, r]));

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="card-h">Settlement waterfall</div>
          <div className="text-sm text-slate-600">Gross settlement → liens → fee → costs → what the client takes home. Math is plain code, not AI.</div>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={reset}>Reset assumptions</button>
          <button className="btn-primary" onClick={save}>Save scenario</button>
        </div>
      </div>
      {saved && <div className="mt-2 text-xs text-emerald-700">{saved}</div>}

      <div className="mt-4 grid gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-2">
          <div>
            <div className="flex items-baseline justify-between">
              <label className="text-sm font-medium">Gross settlement</label>
              <span className="text-2xl font-bold tabular-nums">{money(gross)}</span>
            </div>
            <input type="range" min={0} max={Math.round(wf.max_gross)} step={1000} value={gross}
              onChange={(e) => setGross(Number(e.target.value))} className="w-full accent-indigo-600" />
            <div className="flex flex-wrap gap-1 text-xs">
              {cov && <button className="chip bg-emerald-50 text-emerald-700" onClick={() => setGross(cov)}>coverage cap {money(cov)}</button>}
              {cv && <button className="chip bg-indigo-50 text-indigo-700" onClick={() => setGross(cv)}>case value {money(cv)}</button>}
              {res?.breakeven_gross && <button className="chip bg-slate-100 text-slate-700" onClick={() => setGross(Math.ceil(res.breakeven_gross / 1000) * 1000)}>
                break-even {money(res.breakeven_gross)}</button>}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-sm font-medium">Attorney fee</label>
            <input type="number" step={0.1} min={0} max={50} value={Math.round(fee * 1000) / 10}
              onChange={(e) => setFee(Number(e.target.value) / 100)} className="w-20 rounded border px-2 py-1 text-right" />
            <span className="text-sm">%</span>
            <span className="chip bg-amber-100 text-amber-800">assumption</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="card-h">Client net</div>
              <div className={`text-3xl font-bold tabular-nums ${res?.client_net < 0 ? "text-rose-600" : "text-emerald-700"}`}>{money(res?.client_net)}</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="card-h">Saved by negotiating</div>
              <div className="text-3xl font-bold tabular-nums text-indigo-700">{money(res?.liens.reduce((a: number, r: any) => a + r.saved, 0))}</div>
            </div>
          </div>
          {res?.shortfall && <div className="rounded-lg bg-rose-50 p-2 text-sm text-rose-800">At this amount the liens are not all covered; the client would net nothing.</div>}
          <ul className="space-y-0.5 text-xs text-slate-500">
            {wf.assumptions.map((a: string, i: number) => <li key={i}>⚠ {a}</li>)}
          </ul>
        </div>
        <div className="h-80 lg:col-span-3">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} margin={{ top: 10, right: 10, bottom: 50, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" interval={0} angle={-30} textAnchor="end" tick={{ fontSize: 10 }} height={60} />
              <YAxis tickFormatter={(v) => `$${Math.round(v / 1000)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any, n: any, p: any) => (n === "bar" ? money(p.payload.value) : null)} labelStyle={{ fontWeight: 600 }} />
              <ReferenceLine y={0} stroke="#94a3b8" />
              <Bar dataKey="base" stackId="a" fill="transparent" isAnimationActive={false} />
              <Bar dataKey="bar" stackId="a" isAnimationActive={false} radius={[3, 3, 0, 0]}>
                {chart.map((s: any, i: number) => (
                  <Cell key={i} fill={s.kind === "gross" ? "#6366f1" : s.kind === "net" ? (s.value < 0 ? "#f43f5e" : "#10b981") :
                    s.kind === "lien" ? STATUS[s.status as keyof typeof STATUS].color : "#94a3b8"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="py-1">Order</th><th>Lien / bill</th><th className="text-right">Billed</th><th className="w-56">Negotiate down</th>
              <th className="text-right">Pay</th><th>At this gross</th><th>Source</th></tr>
          </thead>
          <tbody className="divide-y">
            {liens.map((l, i) => {
              const r = byName[l.name];
              return (
                <tr key={l.name} className={l.include ? "" : "opacity-40"}>
                  <td className="py-1.5">
                    <div className="flex items-center gap-1">
                      <input type="checkbox" checked={l.include} onChange={(e) => setLien(i, { include: e.target.checked })} title="Include in the waterfall" />
                      <button className="px-1 text-slate-400 hover:text-slate-800" onClick={() => move(i, -1)}>▲</button>
                      <button className="px-1 text-slate-400 hover:text-slate-800" onClick={() => move(i, 1)}>▼</button>
                      <span className="tabular-nums text-slate-400">{r?.position ?? "–"}</span>
                    </div>
                  </td>
                  <td>{l.name} {l.kind === "lien" && <span className="chip bg-violet-100 text-violet-800">asserted lien</span>}</td>
                  <td className="text-right tabular-nums">{money(l.amount)}</td>
                  <td>
                    <div className="flex items-center gap-2 px-2">
                      <input type="range" min={0} max={0.6} step={0.05} value={l.reduction} className="flex-1 accent-indigo-600"
                        onChange={(e) => setLien(i, { reduction: Number(e.target.value) })} />
                      <span className="w-10 text-right tabular-nums text-xs">−{Math.round(l.reduction * 100)}%</span>
                    </div>
                  </td>
                  <td className="text-right tabular-nums">{r ? money(r.net) : "—"}</td>
                  <td className="pl-3">{r && <span className={`chip ${STATUS[r.status as keyof typeof STATUS].cls}`}>{STATUS[r.status as keyof typeof STATUS].label}</span>}</td>
                  <td><div className="flex gap-1">{(sources[l.name] || []).slice(0, 2).map((s: any, k: number) => <Cite key={k} src={s} />)}</div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          Case costs from Clio: {money(res?.costs)}
          {wf.expenses.slice(0, 5).map((e: any, i: number) => <Cite key={i} src={e.source} label={money(e.amount)} />)}
        </div>
      </div>
    </div>
  );
}
