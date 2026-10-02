import Snapshot from "../components/Snapshot";
import KpiCards from "../components/KpiCards";
import ChangesFeed from "../components/ChangesFeed";
import Attention from "../components/Attention";
import Top10 from "../components/Top10";
import Injuries from "../components/Injuries";
import Waterfall from "../components/Waterfall";
import Tracker from "../components/Tracker";
import Timeline from "../components/Timeline";
import Heatmap from "../components/Heatmap";
import DigDeep from "../components/DigDeep";

export default function Dashboard({ d, mode }: { d: any; mode: "brief" | "deep" }) {
  return (
    <div className="space-y-4">
      <Snapshot d={d} />
      <KpiCards d={d} />
      {mode === "brief" ? (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2"><ChangesFeed d={d} /></div>
            <Attention d={d} />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2"><Top10 d={d} /></div>
            <Injuries d={d} />
          </div>
          <Tracker d={d} />
          <Waterfall d={d} />
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2"><Timeline d={d} /></div>
            <Heatmap d={d} />
          </div>
        </>
      ) : (
        <>
          <DigDeep d={d} />
          <Timeline d={d} />
        </>
      )}
    </div>
  );
}
