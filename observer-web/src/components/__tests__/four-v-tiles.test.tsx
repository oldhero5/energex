import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// Mock echarts to avoid canvas errors in jsdom
const chartInstance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
vi.mock("echarts/core", () => ({
  use: vi.fn(),
  init: vi.fn(() => chartInstance),
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));
vi.mock("echarts/charts", () => ({ PieChart: {} }));
vi.mock("echarts/components", () => ({
  TooltipComponent: {},
  LegendComponent: {},
}));
vi.mock("echarts", () => ({
  use: vi.fn(),
  init: vi.fn(() => chartInstance),
}));

import { FourVTiles } from "../four-v-tiles";
import type { OverviewMetrics } from "@/lib/api";

const metrics: OverviewMetrics = {
  volume: { libraries: 3, symbols: 42, rows: 1_500_000 },
  velocity: { ok: 38, stale: 3, error: 1 },
  variety: { schemas: 5, revision_modes: ["snapshot", "append"] },
  veracity: { broken: 4, broken_symbols: [] },
};

describe("FourVTiles", () => {
  it("renders volume stats", () => {
    render(<FourVTiles metrics={metrics} />);
    expect(screen.getByText("Volume")).toBeInTheDocument();
    // libraries=3 appears, may also match stale=3 — use getAllByText
    expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("42")).toBeInTheDocument(); // symbols
  });

  it("renders variety info", () => {
    render(<FourVTiles metrics={metrics} />);
    expect(screen.getByText("Variety")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument(); // schemas
  });

  it("renders veracity broken count", () => {
    render(<FourVTiles metrics={metrics} />);
    expect(screen.getByText("Veracity")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument(); // broken
  });

  it("renders velocity section", () => {
    render(<FourVTiles metrics={metrics} />);
    expect(screen.getByText("Velocity")).toBeInTheDocument();
    expect(screen.getByText("38")).toBeInTheDocument(); // ok count
  });
});
