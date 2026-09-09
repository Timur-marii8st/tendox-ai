import { PilotDashboard } from "@/app/pilot-dashboard";
import { loadDashboard } from "@/lib/procurement-api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const dashboard = await loadDashboard();
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <PilotDashboard
        dashboard={dashboard}
        demoMode={process.env.PROCUREMENT_DEMO_MODE === "true"}
        nowIso={new Date().toISOString()}
      />
    </main>
  );
}
