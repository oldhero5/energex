import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock echarts to avoid canvas errors in jsdom
const chartInstance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() };
vi.mock("echarts/core", () => ({
  use: vi.fn(),
  init: vi.fn(() => chartInstance),
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));
vi.mock("echarts/charts", () => ({ LineChart: {} }));
vi.mock("echarts/components", () => ({
  TooltipComponent: {},
  GridComponent: {},
  DataZoomComponent: {},
}));

import { SeriesChart } from "../series-chart";

const SERIES_RESPONSE = {
  library: "power.load",
  symbol: "erco",
  as_of: "2026-06-03T00:00:00Z",
  columns: ["Datetime", "instrument_id", "valid_time", "value"],
  rows: [
    { valid_time: "2026-06-01T00:00:00+00:00", instrument_id: "ERCOT.LOAD", value: 40000.0 },
  ],
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("SeriesChart contract", () => {
  it("renders chart container without throwing when response includes columns + as_of", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => SERIES_RESPONSE,
    } as Response);

    render(
      <SeriesChart library="power.load" symbol="erco" vintageAsOfs={["2026-06-03T00:00:00Z"]} />
    );

    // Chart container must be rendered
    const container = await screen.findByRole("img", { name: /series chart/i }).catch(() => null) ??
      await screen.findByLabelText(/series chart/i);
    expect(container).toBeInTheDocument();
  });

  it("does not throw when response is missing columns (defensive guard)", async () => {
    const incompleteResponse = {
      library: "power.load",
      symbol: "erco",
      // no columns, no as_of — old backend shape
      rows: [{ valid_time: "2026-06-01T00:00:00+00:00", value: 40000.0 }],
    };

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => incompleteResponse,
    } as Response);

    // Should not throw — firstValueColumn guard handles missing columns
    expect(() =>
      render(
        <SeriesChart library="power.load" symbol="erco" vintageAsOfs={[]} />
      )
    ).not.toThrow();
  });
});
