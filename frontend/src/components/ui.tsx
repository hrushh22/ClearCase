import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/** Section title with an icon tile and an optional note on the right. */
export function SectionHeader({ icon: Icon, title, note, children }: { icon: any; title: string; note?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2.5">
      <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-rose-50 text-rose-500"><Icon size={17} aria-hidden /></div>
      <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">{title}</h2>
      {note && <div className="text-xs text-slate-500">{note}</div>}
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </div>
  );
}

/** Show the first `limit` items; the rest behind "Show all". Nothing is removed, only folded. */
export function ShowMore<T>({ items, limit, render, className = "space-y-1.5", empty }: {
  items: T[]; limit: number; render: (item: T, i: number) => ReactNode; className?: string; empty?: ReactNode;
}) {
  const [all, setAll] = useState(false);
  if (!items.length) return <>{empty ?? <div className="text-xs text-slate-400">None</div>}</>;
  const shown = all ? items : items.slice(0, limit);
  return (
    <div>
      <div className={className}>{shown.map(render)}</div>
      {items.length > limit && (
        <button onClick={() => setAll(!all)} className="btn-ghost mt-1 px-2 py-1 text-xs text-rose-600" aria-expanded={all}>
          {all ? "Show less" : `Show all ${items.length}`}<ChevronDown size={13} className={`transition ${all ? "rotate-180" : ""}`} />
        </button>
      )}
    </div>
  );
}
