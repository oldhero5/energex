"use client";

import { useEffect, useState } from "react";

interface FailureRow {
  check: string;
  column: string | null;
  failure_case: string;
}

interface QualityResponse {
  library: string;
  symbol: string;
  passed: boolean | null;
  failures: FailureRow[];
  gaps: number;
  anomalies: Record<string, unknown> | null;
  anomalies_note: string | null;
}

interface Props {
  library: string;
  symbol: string;
}

export function QualityPanel({ library, symbol }: Props) {
  const [data, setData] = useState<QualityResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(`/api/observer/symbol/${library}/${symbol}/quality`)
      .then((r) => {
        if (!r.ok) throw new Error(`quality fetch: ${r.status}`);
        return r.json() as Promise<QualityResponse>;
      })
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [library, symbol]);

  if (loading) {
    return <p className="text-sm text-muted py-6 text-center">Loading quality report…</p>;
  }

  if (error) {
    return (
      <div className="rounded border border-fail/30 bg-fail/10 px-3 py-2 text-xs text-fail">
        {error}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-4">
      {/* Gate verdict */}
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted">Quality gate</span>
        {data.passed === null ? (
          <span className="rounded px-2 py-0.5 text-xs font-medium bg-elev border border-line-soft text-muted">
            No schema registered
          </span>
        ) : data.passed ? (
          <span className="rounded px-2 py-0.5 text-xs font-medium bg-ok/15 border border-ok/30 text-ok">
            pass
          </span>
        ) : (
          <span className="rounded px-2 py-0.5 text-xs font-medium bg-fail/15 border border-fail/30 text-fail">
            fail
          </span>
        )}
      </div>

      {/* Failures table */}
      {data.failures.length > 0 && (
        <div>
          <p className="text-xs text-muted mb-2">Failures ({data.failures.length})</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line-soft">
                  <th className="py-1.5 pr-4 text-left text-muted font-medium">Check</th>
                  <th className="py-1.5 pr-4 text-left text-muted font-medium">Column</th>
                  <th className="py-1.5 text-left text-muted font-medium">Failure case</th>
                </tr>
              </thead>
              <tbody>
                {data.failures.map((f, i) => (
                  <tr key={i} className="border-b border-line-soft/40 hover:bg-elev/50">
                    <td className="py-1.5 pr-4 num text-fail">{f.check}</td>
                    <td className="py-1.5 pr-4 num text-fg-2">{f.column ?? "—"}</td>
                    <td className="py-1.5 num text-fg-2">{f.failure_case}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data.failures.length === 0 && data.passed && (
        <p className="text-xs text-ok">No check failures.</p>
      )}

      {/* Gaps */}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-muted">Data gaps</span>
        <span className={`num ${data.gaps > 0 ? "text-warn" : "text-ok"}`}>{data.gaps}</span>
      </div>

      {/* Anomalies */}
      {data.anomalies_note && (
        <div className="rounded border border-line-soft bg-elev/40 px-3 py-2 text-xs text-muted">
          {data.anomalies_note}
        </div>
      )}

      {data.anomalies && !data.anomalies_note && (
        <div>
          <p className="text-xs text-muted mb-2">Anomalies</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Object.entries(data.anomalies).map(([key, val]) => (
              <div key={key} className="rounded border border-line-soft bg-elev px-3 py-2 space-y-0.5">
                <p className="text-[10px] text-muted uppercase tracking-wider">{key}</p>
                <p className="num text-sm text-fg">{String(val)}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
