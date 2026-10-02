import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { api, fmtDate, SOURCE_LABEL, type Src } from "../lib/api";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const Ctx = createContext<(s: Src) => void>(() => {});
export const useSource = () => useContext(Ctx);

/** Small clickable citation chip. Every fact on screen carries one. */
export function Cite({ src, label, className = "" }: { src?: Src | null; label?: string; className?: string }) {
  const open = useSource();
  if (!src || !src.source_type) return null;
  const text = label ?? `${SOURCE_LABEL[src.source_type] ?? src.source_type}${src.page ? ` p.${src.page}` : ""}`;
  return (
    <button
      onClick={(e) => { e.stopPropagation(); open(src); }}
      title={src.quote ? `"${src.quote}"` : "Open source"}
      className={`chip bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-100 whitespace-nowrap ${className}`}
    >
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M14 3h7v7M10 14L21 3M21 14v7H3V3h7" /></svg>
      {text}
    </button>
  );
}

export function SourceProvider({ children }: { children: ReactNode }) {
  const [src, setSrc] = useState<Src | null>(null);
  return (
    <Ctx.Provider value={setSrc}>
      {children}
      {src && <Drawer src={src} onClose={() => setSrc(null)} />}
    </Ctx.Provider>
  );
}

function highlight(text: string, quote?: string | null) {
  if (!quote) return [text];
  const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ");
  const idx = norm(text).indexOf(norm(quote).trim());
  if (idx < 0) return [text];
  // map normalized index back to original (collapse whitespace runs)
  let o = 0, n = 0;
  const map: number[] = [];
  while (o < text.length) {
    map[n] = o;
    if (/\s/.test(text[o])) { while (o + 1 < text.length && /\s/.test(text[o + 1])) o++; }
    o++; n++;
  }
  map[n] = text.length;
  const start = map[idx] ?? 0;
  const end = map[idx + norm(quote).trim().length] ?? text.length;
  return [text.slice(0, start), <mark key="q" className="quote">{text.slice(start, end)}</mark>, text.slice(end)];
}

function Drawer({ src, onClose }: { src: Src; onClose: () => void }) {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setData(null); setErr(null);
    api.source(src.source_type, src.source_id).then(setData).catch((e) => setErr(String(e.message || e)));
  }, [src.source_type, src.source_id]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30" onClick={onClose}>
      <div className="h-full w-full max-w-3xl bg-white shadow-2xl flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b px-5 py-3">
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-indigo-600">
              {SOURCE_LABEL[src.source_type] ?? src.source_type} · opened from Clio record {src.source_id}
            </div>
            <div className="truncate font-semibold">{data?.title || data?.name || "Loading…"}</div>
            {data?.date && <div className="text-xs text-slate-500">{fmtDate(data.date)}</div>}
          </div>
          <button className="btn-ghost" onClick={onClose}>Close ✕</button>
        </div>
        {src.quote && (
          <div className="border-b bg-amber-50 px-5 py-2 text-sm text-amber-900">
            <span className="font-semibold">Cited text: </span>“{src.quote}”
          </div>
        )}
        <div className="flex-1 overflow-auto">
          {err && <div className="p-5 text-red-600">{err}</div>}
          {data && src.source_type === "document" && <PdfView doc={data} src={src} />}
          {data && src.source_type !== "document" && (
            <div className="p-5">
              {data.meta?.senders && (
                <div className="mb-3 text-xs text-slate-500">
                  {data.meta.type} · from {data.meta.senders.map((p: any) => p.name).join(", ")} to{" "}
                  {data.meta.receivers?.map((p: any) => p.name).join(", ")}
                </div>
              )}
              {data.meta?.status && <div className="mb-3 text-xs text-slate-500">Status: {data.meta.status} · due {fmtDate(data.meta.due_at)}</div>}
              <pre className="whitespace-pre-wrap font-sans text-[15px] leading-relaxed text-slate-800">{highlight(data.text, src.quote)}</pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PdfView({ doc, src }: { doc: any; src: Src }) {
  const [page, setPage] = useState<number>(src.page || 1);
  const [loc, setLoc] = useState<any>(null);
  const [pdf, setPdf] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    pdfjs.getDocument({ url: `/api/documents/${doc.id}/file` }).promise.then((p) => !cancelled && setPdf(p));
    return () => { cancelled = true; };
  }, [doc.id]);

  useEffect(() => {
    if (!src.quote) return;
    api.locate(doc.id, src.quote, src.page).then((l) => { setLoc(l); setPage(l.page); }).catch(() => setLoc({ bboxes: [], note: "Could not locate the text; showing the cited page." }));
  }, [doc.id, src.quote, src.page]);

  useEffect(() => {
    if (!pdf || !canvasRef.current) return;
    let task: any;
    setLoading(true);
    pdf.getPage(page).then((pg) => {
      const vp = pg.getViewport({ scale });
      const c = canvasRef.current!;
      c.width = vp.width; c.height = vp.height;
      task = pg.render({ canvas: c, canvasContext: c.getContext("2d")!, viewport: vp } as any);
      task.promise.then(() => setLoading(false)).catch(() => {});
    });
    return () => task?.cancel?.();
  }, [pdf, page, scale]);

  const boxes = loc && loc.page === page ? loc.bboxes : [];
  return (
    <div>
      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b bg-white px-5 py-2 text-sm">
        <span className="chip bg-slate-100 text-slate-700">{doc.folder}</span>
        {doc.scanned_pages > 0 && <span className="chip bg-amber-100 text-amber-800">scanned · OCR</span>}
        <div className="ml-auto flex items-center gap-1">
          <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
          <span className="tabular-nums">Page {page} / {doc.page_count}</span>
          <button className="btn-ghost" disabled={page >= doc.page_count} onClick={() => setPage(page + 1)}>›</button>
          <button className="btn-ghost" onClick={() => setScale(Math.max(0.6, scale - 0.2))}>−</button>
          <button className="btn-ghost" onClick={() => setScale(Math.min(2.4, scale + 0.2))}>+</button>
          <a className="btn-ghost" href={`/api/documents/${doc.id}/file#page=${page}`} target="_blank">Open PDF</a>
        </div>
      </div>
      {loc && (
        <div className={`px-5 py-1.5 text-xs ${boxes.length ? "text-emerald-700" : "text-amber-700"}`}>
          {boxes.length
            ? `Highlighted on page ${loc.page} (${loc.match === "exact" ? "exact match" : `fuzzy match ${loc.score}%`}${loc.method === "ocr" ? ", from OCR of the scan" : ""}).`
            : loc.note || "Showing the cited page."}
        </div>
      )}
      <div className="flex justify-center bg-slate-100 p-4">
        <div className="relative shadow">
          <canvas ref={canvasRef} className={loading ? "opacity-60" : ""} />
          {boxes.map((b: number[], i: number) => (
            <div key={i} className="absolute rounded-sm border-2 border-amber-500 bg-amber-300/35"
              style={{ left: b[0] * scale - 2, top: b[1] * scale - 2, width: (b[2] - b[0]) * scale + 4, height: (b[3] - b[1]) * scale + 4 }} />
          ))}
        </div>
      </div>
    </div>
  );
}
