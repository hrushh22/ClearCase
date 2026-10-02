import { useMemo, useState } from "react";
import { Cite, useSource } from "./SourceViewer";
import { fmtDate, money, SOURCE_LABEL } from "../lib/api";

const STATUS_CLS: Record<string, string> = {
  supported: "bg-emerald-100 text-emerald-800", partial: "bg-amber-100 text-amber-800", quote_ok: "bg-sky-100 text-sky-800",
};

export default function DigDeep({ d }: { d: any }) {
  const facts: any[] = d.facts;
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [src, setSrc] = useState("");
  const open = useSource();
  const types = useMemo(() => [...new Set(facts.map((f) => f.type))].sort(), [facts]);
  const srcs = useMemo(() => [...new Set(facts.map((f) => f.source_type))].sort(), [facts]);
  const shown = useMemo(() => {
    const ql = q.toLowerCase();
    return facts
      .filter((f) => (!type || f.type === type) && (!src || f.source_type === src) &&
        (!ql || `${f.text} ${f.quote} ${f.entity || ""}`.toLowerCase().includes(ql)))
      .sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  }, [facts, q, type, src]);
  const hidden = d.fact_stats?.unsupported || 0;

  return (
    <div className="space-y-4">
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search every verified fact…"
            className="min-w-[260px] flex-1 rounded-lg border px-3 py-2" />
          <select value={type} onChange={(e) => setType(e.target.value)} className="rounded-lg border px-2 py-2">
            <option value="">All types</option>{types.map((t) => <option key={t}>{t}</option>)}
          </select>
          <select value={src} onChange={(e) => setSrc(e.target.value)} className="rounded-lg border px-2 py-2">
            <option value="">All sources</option>{srcs.map((t) => <option key={t} value={t}>{SOURCE_LABEL[t] || t}</option>)}
          </select>
        </div>
        <div className="mt-2 text-xs text-slate-500">
          {shown.length} of {facts.length} facts shown · {hidden} claims hidden because the verifier could not find support in the cited source ·
          extractors: {Object.entries(d.extractors || {}).map(([k, v]) => `${k} ${v}`).join(", ")}
        </div>
        <div className="mt-3 max-h-[70vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white text-left text-xs uppercase text-slate-500">
              <tr><th className="py-1">Date</th><th>Type</th><th>Fact</th><th>Amount</th><th>Check</th><th>Source</th></tr>
            </thead>
            <tbody className="divide-y">
              {shown.slice(0, 600).map((f) => (
                <tr key={f.fact_id} className="align-top hover:bg-slate-50">
                  <td className="whitespace-nowrap py-1.5 pr-2 text-xs tabular-nums text-slate-500">{fmtDate(f.date)}</td>
                  <td className="pr-2"><span className="chip bg-slate-100 text-slate-700">{f.type}</span></td>
                  <td className="pr-2">{f.text}{f.entity && <span className="text-xs text-slate-500"> · {f.entity}</span>}</td>
                  <td className="whitespace-nowrap pr-2 tabular-nums">{f.amount ? money(f.amount, 2) : ""}</td>
                  <td className="pr-2"><span title={f.verify_reason} className={`chip ${STATUS_CLS[f.verify_status] || "bg-slate-100"}`}>{f.verify_status.replace("_", " ")}</span></td>
                  <td><Cite src={f} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card p-5">
        <div className="card-h">Documents in the file</div>
        <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {d.documents.map((doc: any) => (
            <button key={doc.id} onClick={() => open({ source_type: "document", source_id: doc.id, page: 1 })}
              className="rounded-lg border p-3 text-left hover:border-indigo-300 hover:bg-indigo-50/40">
              <div className="truncate text-sm font-medium">{doc.name}</div>
              <div className="text-xs text-slate-500">{doc.folder} · {doc.page_count} pages{doc.scanned_pages ? ` · ${doc.scanned_pages} scanned` : ""} · {fmtDate(doc.received_at)}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
