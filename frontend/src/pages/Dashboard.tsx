import { useState } from "react";
import { BookOpenText, CircleDollarSign, HeartPulse, Search, Sparkles, Sun } from "lucide-react";
import Hero from "../components/Hero";
import ChangesFeed from "../components/ChangesFeed";
import Attention from "../components/Attention";
import Top10 from "../components/Top10";
import Injuries from "../components/Injuries";
import Waterfall from "../components/Waterfall";
import Tracker from "../components/Tracker";
import Timeline from "../components/Timeline";
import Heatmap from "../components/Heatmap";
import DigDeep from "../components/DigDeep";

type Tab = "today" | "medical" | "money" | "story";
const TAB_KEY = "clearcase.tab";

export default function Dashboard({ d, mode, setMode }: { d: any; mode: "brief" | "deep"; setMode: (m: "brief" | "deep") => void }) {
  const [tab, setTabState] = useState<Tab>(() => {
    try { return (localStorage.getItem(TAB_KEY) as Tab) || "today"; } catch { return "today"; }
  });
  const setTab = (t: Tab) => { setTabState(t); try { localStorage.setItem(TAB_KEY, t); } catch { /* private mode */ } };
  const overdue = d.attention?.overdue?.length || 0;
  const tabs: { id: Tab; label: string; icon: any; badge?: string | number; hint: string }[] = [
    { id: "today", label: "Today", icon: Sun, badge: overdue || undefined, hint: "What changed, what's late, what matters" },
    { id: "medical", label: "Medical", icon: HeartPulse, badge: d.injuries?.injuries?.length || undefined, hint: "Injuries and who treated them" },
    { id: "money", label: "Money", icon: CircleDollarSign, hint: "Settlement waterfall and liens" },
    { id: "story", label: "Story", icon: BookOpenText, hint: "Stage, timeline and contact history" },
  ];

  return (
    <div className="space-y-5">
      <Hero d={d} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        {mode === "brief" ? (
          <div className="tabs" role="tablist" aria-label="Case digest sections">
            {tabs.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} className="tab" onClick={() => setTab(t.id)} title={t.hint}>
                <t.icon size={16} aria-hidden />{t.label}
                {t.badge !== undefined && (
                  <span className={`rounded-full px-1.5 text-[11px] font-semibold ${tab === t.id ? "bg-white/25 text-white" : "bg-rose-100 text-rose-700"}`}>{t.badge}</span>
                )}
              </button>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-slate-600"><Search size={16} className="text-rose-500" />Every verified fact, searchable</div>
        )}
        <div className="tabs" role="group" aria-label="Detail level">
          <button className="tab" aria-selected={mode === "brief"} onClick={() => setMode("brief")}><Sparkles size={15} />2-minute brief</button>
          <button className="tab" aria-selected={mode === "deep"} onClick={() => setMode("deep")}><Search size={15} />Dig deep</button>
        </div>
      </div>

      {mode === "deep" ? (
        <div key="deep" className="fade-up space-y-5">
          <DigDeep d={d} />
          <Timeline d={d} />
        </div>
      ) : (
        <div key={tab} className="fade-up space-y-5" role="tabpanel">
          {tab === "today" && (
            <>
              <div className="grid gap-5 lg:grid-cols-3 2xl:grid-cols-5">
                <div className="lg:col-span-2 2xl:col-span-3"><ChangesFeed d={d} /></div>
                <div className="2xl:col-span-2"><Attention d={d} /></div>
              </div>
              <Top10 d={d} />
            </>
          )}
          {tab === "medical" && <Injuries d={d} />}
          {tab === "money" && <Waterfall d={d} />}
          {tab === "story" && (
            <>
              <Tracker d={d} />
              <div className="grid gap-5 lg:grid-cols-3 2xl:grid-cols-4">
                <div className="lg:col-span-2 2xl:col-span-3"><Timeline d={d} /></div>
                <Heatmap d={d} />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
