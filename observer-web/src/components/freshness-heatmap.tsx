import type { HealthRow } from "@/lib/api";

function statusColor(row: HealthRow): string {
  if (row.freshness_status === "error") return "bg-fail/20 border-fail/40 text-fail";
  if (row.freshness_status === "stale") return "bg-warn/20 border-warn/40 text-warn";
  // ok — ramp from green toward ochre based on age_days
  const age = row.age_days ?? 0;
  if (age <= 1) return "bg-ok/20 border-ok/40 text-ok";
  if (age <= 3) return "bg-ok/10 border-ok/30 text-ok";
  return "bg-accent-tint border-accent-dim/40 text-accent";
}

function ageBadge(row: HealthRow): string {
  if (row.age_days === null) return "—";
  if (row.age_days === 0) return "today";
  if (row.age_days === 1) return "1d";
  return `${row.age_days}d`;
}

interface Props {
  rows: HealthRow[];
}

export function FreshnessHeatmap({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="panel p-4">
        <h2 className="mb-3 text-sm font-medium text-muted">Freshness Heatmap</h2>
        <p className="text-sm text-muted">No symbols to display.</p>
      </div>
    );
  }

  // Group by library
  const byLibrary = rows.reduce<Record<string, HealthRow[]>>((acc, r) => {
    (acc[r.library] ??= []).push(r);
    return acc;
  }, {});

  return (
    <div className="panel p-4">
      <h2 className="mb-3 text-sm font-medium text-muted">Freshness Heatmap</h2>
      <div className="space-y-4">
        {Object.entries(byLibrary).map(([lib, libRows]) => (
          <div key={lib}>
            <p className="mb-2 text-xs text-faint">{lib}</p>
            <div className="flex flex-wrap gap-1.5">
              {libRows.map((row) => (
                <div
                  key={`${row.library}/${row.symbol}`}
                  className={`rounded border px-2 py-1 text-xs num ${statusColor(row)}`}
                  title={`${row.symbol} · ${row.freshness_status} · age ${row.age_days ?? "unknown"} days · ${row.row_count?.toLocaleString() ?? "—"} rows`}
                >
                  <div className="font-medium">{row.symbol}</div>
                  <div className="opacity-75">{ageBadge(row)}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
