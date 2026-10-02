import { Cite } from "./SourceViewer";

export default function Injuries({ d }: { d: any }) {
  const inj = d.injuries;
  const scanned = d.documents.filter((x: any) => x.scanned_pages > 0).reduce((a: number, x: any) => a + x.scanned_pages, 0);
  return (
    <div className="card p-5">
      <div className="card-h">Injuries and treatment</div>
      <div className="text-xs text-slate-500">
        from {d.documents.length} documents ({scanned} scanned pages read by OCR) plus notes · {inj.method === "llm" ? "AI summary, every line cited" : "diagnosis lines found by rules"}
      </div>
      <div className="mt-3 max-h-[640px] space-y-3 overflow-auto pr-1">
        {inj.injuries.length === 0 && <div className="text-sm text-slate-500">No injury facts yet.</div>}
        {inj.injuries.map((i: any, k: number) => (
          <div key={k} className="rounded-lg border border-slate-100 p-3">
            {i.body_part && <div className="font-semibold text-rose-700">{i.body_part}</div>}
            <div className="text-sm">{i.finding}</div>
            {i.treatment && <div className="text-sm text-slate-600">Treatment: {i.treatment}</div>}
            {i.status && <div className="text-xs text-slate-500">Status: {i.status}</div>}
            <div className="mt-1 flex flex-wrap gap-1">{i.sources.slice(0, 4).map((s: any, j: number) => <Cite key={j} src={s} />)}</div>
          </div>
        ))}
      </div>
      {inj.providers?.length > 0 && (
        <>
          <div className="card-h mt-4">Who treated</div>
          <ul className="mt-1 space-y-1 text-sm">
            {inj.providers.map((p: any, k: number) => (
              <li key={k} className="flex items-start gap-2">
                <span className="flex-1"><b>{p.name}</b> <span className="text-slate-600">· {p.role}</span></span>
                {p.sources[0] && <Cite src={p.sources[0]} />}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
