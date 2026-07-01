"use client";

import { useEffect, useRef, useState } from "react";
import { AsOfSlider } from "./as-of-slider";

// Lean ECharts import: core + canvas + line
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { TooltipComponent, GridComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, TooltipComponent, GridComponent, DataZoomComponent, CanvasRenderer]);

interface SeriesRow {
  valid_time: string;
  [key: string]: unknown;
}

interface SeriesResponse {
  library: string;
  symbol: string;
  as_of: string | null;
  columns: string[];
  rows: SeriesRow[];
}

interface Props {
  library: string;
  symbol: string;
  vintageAsOfs: string[]; // ordered list of as_of ISOs from /vintages
}

function firstValueColumn(columns: string[] | undefined | null): string | null {
  if (!columns || columns.length === 0) return null;
  // Skip valid_time, return first numeric-looking column
  const skip = new Set(["valid_time", "symbol", "library"]);
  return columns.find((c) => !skip.has(c)) ?? null;
}

export function SeriesChart({ library, symbol, vintageAsOfs }: Props) {
  const [asOf, setAsOf] = useState<string | undefined>(undefined); // undefined = latest
  const [data, setData] = useState<SeriesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  // Fetch series data whenever asOf changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const qs = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
    fetch(`/api/observer/symbol/${library}/${symbol}/series${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`series fetch: ${r.status}`);
        return r.json() as Promise<SeriesResponse>;
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
  }, [asOf, library, symbol]);

  // Render / update ECharts when data changes
  useEffect(() => {
    if (!chartRef.current || !data) return;

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, null, { renderer: "canvas" });
    }

    const col = firstValueColumn(data.columns);
    if (!col) return;

    const xData = data.rows.map((r) => r.valid_time as string);
    const yData = data.rows.map((r) => r[col] as number);

    chartInstance.current.setOption({
      backgroundColor: "transparent",
      grid: { left: 60, right: 20, top: 20, bottom: 40 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        backgroundColor: "var(--panel)",
        borderColor: "var(--line)",
        textStyle: { color: "var(--fg)", fontFamily: "var(--mono)", fontSize: 11 },
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16 }],
      xAxis: {
        type: "category",
        data: xData,
        axisLine: { lineStyle: { color: "var(--line)" } },
        axisLabel: {
          color: "var(--muted)",
          fontFamily: "var(--mono)",
          fontSize: 10,
          rotate: 30,
          interval: Math.max(0, Math.floor(xData.length / 8) - 1),
        },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        splitLine: { lineStyle: { color: "var(--line-soft)" } },
        axisLabel: {
          color: "var(--muted)",
          fontFamily: "var(--mono)",
          fontSize: 10,
        },
      },
      series: [
        {
          name: col,
          type: "line",
          data: yData,
          lineStyle: { color: "var(--accent)", width: 1.5 },
          itemStyle: { color: "var(--accent)" },
          showSymbol: false,
          areaStyle: { color: "var(--accent-tint)", opacity: 0.6 },
        },
      ],
    }, true);

    return () => {
      // Don't dispose here — reuse on re-render
    };
  }, [data]);

  // Dispose on unmount
  useEffect(() => {
    return () => {
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  const valueCol = data ? firstValueColumn(data.columns) : null;

  return (
    <div className="space-y-3">
      <AsOfSlider vintages={vintageAsOfs} onChange={setAsOf} />

      {loading && (
        <div className="flex items-center gap-2 py-8 justify-center text-xs text-muted">
          <span>Loading series data…</span>
        </div>
      )}

      {error && !loading && (
        <div className="rounded border border-fail/30 bg-fail/10 px-3 py-2 text-xs text-fail">
          {error}
        </div>
      )}

      {!loading && !error && data && data.rows.length === 0 && (
        <p className="text-sm text-muted py-6 text-center">No data for this symbol.</p>
      )}

      {!loading && !error && data && data.rows.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className="num text-fg-2">{data.rows.length.toLocaleString()} rows</span>
            {valueCol && <span className="text-faint">· column: <span className="num text-fg-2">{valueCol}</span></span>}
            {data.as_of && (
              <span className="text-faint">· as_of: <span className="num text-accent">{data.as_of}</span></span>
            )}
          </div>
          <div
            ref={chartRef}
            aria-label="series chart"
            style={{ width: "100%", height: 280 }}
          />
        </div>
      )}
    </div>
  );
}
