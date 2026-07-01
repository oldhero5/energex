"use client";

import { useEffect, useRef } from "react";
import type { OverviewMetrics } from "@/lib/api";

// Lean ECharts import: core + canvas + pie only
import * as echarts from "echarts/core";
import { PieChart } from "echarts/charts";
import { TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([PieChart, TooltipComponent, LegendComponent, CanvasRenderer]);

function VelocityDonut({ ok, stale, error }: { ok: number; stale: number; error: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, null, { renderer: "canvas" });
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "item", formatter: "{b}: {c}" },
      series: [
        {
          type: "pie",
          radius: ["55%", "85%"],
          label: { show: false },
          itemStyle: { borderColor: "transparent", borderWidth: 2 },
          data: [
            { name: "ok", value: ok, itemStyle: { color: "var(--ok)" } },
            { name: "stale", value: stale, itemStyle: { color: "var(--warn)" } },
            { name: "error", value: error, itemStyle: { color: "var(--fail)" } },
          ],
        },
      ],
    });
    return () => chart.dispose();
  }, [ok, stale, error]);

  return <div ref={ref} style={{ width: 72, height: 72 }} />;
}

interface Props {
  metrics: OverviewMetrics;
}

export function FourVTiles({ metrics }: Props) {
  const { volume, velocity, variety, veracity } = metrics;
  const totalVelocity = velocity.ok + velocity.stale + velocity.error;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {/* Volume */}
      <div className="panel p-4 space-y-3">
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Volume</h3>
        <div className="space-y-1.5">
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-muted">Libraries</span>
            <span className="num text-lg text-fg">{volume.libraries}</span>
          </div>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-muted">Symbols</span>
            <span className="num text-lg text-fg">{volume.symbols}</span>
          </div>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-muted">Rows</span>
            <span className="num text-sm text-fg-2">{volume.rows.toLocaleString()}</span>
          </div>
        </div>
      </div>

      {/* Velocity */}
      <div className="panel p-4 space-y-3">
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Velocity</h3>
        <div className="flex items-center gap-3">
          <VelocityDonut ok={velocity.ok} stale={velocity.stale} error={velocity.error} />
          <div className="space-y-1 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-ok" />
              <span className="text-muted">ok</span>
              <span className="num text-fg ml-auto">{velocity.ok}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-warn" />
              <span className="text-muted">stale</span>
              <span className="num text-fg ml-auto">{velocity.stale}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-fail" />
              <span className="text-muted">error</span>
              <span className="num text-fg ml-auto">{velocity.error}</span>
            </div>
          </div>
        </div>
        <p className="text-xs text-muted num">{totalVelocity} symbols tracked</p>
      </div>

      {/* Variety */}
      <div className="panel p-4 space-y-3">
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Variety</h3>
        <div className="space-y-1.5">
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-muted">Schemas</span>
            <span className="num text-lg text-fg">{variety.schemas}</span>
          </div>
          <div className="mt-2">
            <p className="text-xs text-muted mb-1">Revision modes</p>
            <div className="flex flex-wrap gap-1">
              {variety.revision_modes.map((mode) => (
                <span
                  key={mode}
                  className="rounded px-1.5 py-0.5 text-xs num bg-elev text-fg-2 border border-line-soft"
                >
                  {mode}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Veracity */}
      <div className="panel p-4 space-y-3">
        <h3 className="text-xs font-medium text-muted uppercase tracking-wider">Veracity</h3>
        <div className="space-y-1.5">
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-muted">Broken</span>
            <span className={`num text-2xl ${veracity.broken > 0 ? "text-fail" : "text-ok"}`}>
              {veracity.broken}
            </span>
          </div>
          {veracity.broken === 0 && (
            <p className="text-xs text-ok">All symbols healthy</p>
          )}
          {veracity.broken > 0 && (
            <p className="text-xs text-muted">
              {veracity.broken} symbol{veracity.broken !== 1 ? "s" : ""} stale or broken
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
