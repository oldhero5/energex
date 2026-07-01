import { apiFetch } from "@/lib/api";
import type { OverviewMetrics, HealthRow } from "@/lib/api";
import { FourVTiles } from "@/components/four-v-tiles";
import { FreshnessHeatmap } from "@/components/freshness-heatmap";
import { BrokenRail } from "@/components/broken-rail";

async function getOverview(): Promise<OverviewMetrics | { error: string } | null> {
  try {
    return await apiFetch<OverviewMetrics>("/metrics/overview");
  } catch (err) {
    console.error("[OverviewPage] getOverview failed:", err);
    const msg = err instanceof Error ? err.message : String(err);
    return { error: msg };
  }
}

async function getHealth(): Promise<{ rows: HealthRow[] } | { error: string } | null> {
  try {
    return await apiFetch<{ rows: HealthRow[] }>("/metrics/health");
  } catch (err) {
    console.error("[OverviewPage] getHealth failed:", err);
    const msg = err instanceof Error ? err.message : String(err);
    return { error: msg };
  }
}

function isAuthError(msg: string): boolean {
  return /: 40[13]/.test(msg);
}

function ErrorBanner({ message }: { message: string }) {
  const authError = isAuthError(message);
  return (
    <div className="panel p-4">
      <p className="text-sm text-muted">
        {authError
          ? "Couldn't load data — you may not have access. Try signing in again."
          : "Couldn't load data — confirm observer-api is running and that you're signed in with access."}
      </p>
    </div>
  );
}

export default async function OverviewPage() {
  const [overview, health] = await Promise.all([getOverview(), getHealth()]);

  const overviewError = overview == null || "error" in overview;
  const healthError = health == null || "error" in health;

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-fg">Overview</h1>

      {overviewError ? (
        <ErrorBanner
          message={overview != null && "error" in overview ? overview.error : "unavailable"}
        />
      ) : (
        <FourVTiles metrics={overview} />
      )}

      {healthError ? (
        <ErrorBanner
          message={health != null && "error" in health ? health.error : "unavailable"}
        />
      ) : (
        <>
          <FreshnessHeatmap rows={health.rows} />
          <BrokenRail
            items={
              overviewError
                ? health.rows
                    .filter((r) => r.freshness_status !== "ok")
                    .map((r) => ({ library: r.library, symbol: r.symbol }))
                : overview.veracity.broken_symbols
            }
          />
        </>
      )}
    </div>
  );
}
