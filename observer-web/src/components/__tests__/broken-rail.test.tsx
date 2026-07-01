import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BrokenRail } from "../broken-rail";

describe("BrokenRail", () => {
  it("lists broken symbols", () => {
    render(<BrokenRail items={[{ library: "power.load", symbol: "erco" }]} />);
    expect(screen.getByText(/power\.load/)).toBeInTheDocument();
    expect(screen.getByText("erco")).toBeInTheDocument();
  });
  it("shows an all-clear when empty", () => {
    render(<BrokenRail items={[]} />);
    expect(screen.getByText(/no broken data/i)).toBeInTheDocument();
  });
});
