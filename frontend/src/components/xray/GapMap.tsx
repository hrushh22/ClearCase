import { fmtDate, money } from "../../lib/api";

/** Care chain: incident -> each provider by first appearance -> pending steps. Missing pieces are drawn broken. */
export default function GapMap({ x, onOpenIssue }: { x: any; onOpenIssue: (id: string) => void }) {
  const chain: any[] = x.gap_chain || [];
  if (!chain.length) return <div className="text-sm text-slate-500">No treating providers found in the file.</div>;
  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex min-w-max items-stretch gap-0">
        <Step title="Incident" sub={fmtDate(x.incident_date)} ok glyph="⚑" />
        {chain.map((s, k) => {
          const pending = s.pending;
          const missing = !pending && (s.issues?.length > 0);
          return (
            <div key={k} className="flex items-stretch">
              <Connector broken={pending || missing} />
              <button disabled={!s.issues?.length} onClick={() => s.issues?.[0] && onOpenIssue(s.issues[0])}
                className={`w-44 rounded-2xl border border-rose-100 bg-white p-3 text-left transition hover:-translate-y-0.5 hover:shadow-md ${pending ? "border-dashed border-amber-400 bg-amber-50" : missing ? "border-amber-300 bg-white" : "bg-white"}
                  ${s.issues?.length ? "hover:ring-2 hover:ring-amber-300" : ""}`}>
                <div className="flex items-center gap-1 text-[11px] text-slate-500">{pending ? "pending" : fmtDate(s.first_date)}</div>
                <div className="line-clamp-2 text-sm font-semibold">{pending ? s.name : s.name}</div>
                {!pending && <div className="line-clamp-1 text-[11px] text-slate-500">{s.role}</div>}
                {!pending && (
                  <div className="mt-2 flex flex-wrap gap-1 text-[10px]">
                    <span className={`chip ${s.records.length ? "bg-emerald-50 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>{s.records.length ? "✓ records" : "? records"}</span>
                    <span className={`chip ${s.bills.length || s.charges ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                      {s.bills.length || s.charges ? `✓ bill${s.charges ? " " + money(s.charges) : ""}` : "– bill"}
                    </span>
                  </div>
                )}
                {pending && <div className="mt-1 text-[11px] text-amber-800">? No date or report found. Click for details.</div>}
              </button>
            </div>
          );
        })}
      </div>
      <div className="mt-2 text-xs text-slate-500">Broken links mark where ClearCase could not locate expected supporting evidence in the available case file.</div>
    </div>
  );
}

function Connector({ broken }: { broken: boolean }) {
  return (
    <div className="flex w-8 items-center" aria-label={broken ? "missing link" : "documented link"}>
      <div className={`h-0.5 w-full ${broken ? "border-t-2 border-dashed border-amber-400" : "bg-rose-400"}`} />
    </div>
  );
}

function Step({ title, sub, ok, glyph }: any) {
  return (
    <div className={`w-32 rounded-xl border p-3 ${ok ? "border-rose-300 bg-rose-50" : ""}`}>
      <div className="text-lg" aria-hidden>{glyph}</div>
      <div className="text-sm font-semibold">{title}</div>
      <div className="text-[11px] text-slate-500">{sub}</div>
    </div>
  );
}
