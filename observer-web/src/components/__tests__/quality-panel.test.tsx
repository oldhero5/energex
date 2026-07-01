import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QualityPanel } from "../quality-panel";

beforeEach(() => {
  vi.restoreAllMocks();
});

function mockQualityFetch(passed: boolean | null) {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      library: "power.load",
      symbol: "erco",
      passed,
      failures: passed === false ? [{ check: "not_null", column: "value", failure_case: "2 nulls" }] : [],
      gaps: 0,
      anomalies: null,
      anomalies_note: null,
    }),
  } as Response);
}

describe("QualityPanel gate verdict", () => {
  it("renders pass badge when passed=true", async () => {
    mockQualityFetch(true);
    render(<QualityPanel library="power.load" symbol="erco" />);
    expect(await screen.findByText("pass")).toBeInTheDocument();
    expect(screen.queryByText("fail")).not.toBeInTheDocument();
    expect(screen.queryByText(/no schema/i)).not.toBeInTheDocument();
  });

  it("renders fail badge when passed=false", async () => {
    mockQualityFetch(false);
    render(<QualityPanel library="power.load" symbol="erco" />);
    expect(await screen.findByText("fail")).toBeInTheDocument();
    expect(screen.queryByText("pass")).not.toBeInTheDocument();
    expect(screen.queryByText(/no schema/i)).not.toBeInTheDocument();
  });

  it("renders neutral 'No schema registered' badge when passed=null (not a fail badge)", async () => {
    mockQualityFetch(null);
    render(<QualityPanel library="power.load" symbol="erco" />);
    expect(await screen.findByText(/no schema registered/i)).toBeInTheDocument();
    // Must NOT show fail — null means unmapped, not broken
    expect(screen.queryByText("fail")).not.toBeInTheDocument();
    expect(screen.queryByText("pass")).not.toBeInTheDocument();
  });
});
