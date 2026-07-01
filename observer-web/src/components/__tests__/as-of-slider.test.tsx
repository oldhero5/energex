import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AsOfSlider } from "../as-of-slider";

describe("AsOfSlider", () => {
  it("emits the chosen as_of", () => {
    const onChange = vi.fn();
    render(<AsOfSlider vintages={["2026-06-02T00:00:00Z", "2026-06-05T00:00:00Z"]} onChange={onChange} />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
    expect(onChange).toHaveBeenCalledWith("2026-06-02T00:00:00Z");
  });

  it("emits undefined for 'latest' position", () => {
    const onChange = vi.fn();
    render(<AsOfSlider vintages={["2026-06-02T00:00:00Z", "2026-06-05T00:00:00Z"]} onChange={onChange} />);
    // Move to a vintage first, then back to latest
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
    fireEvent.change(screen.getByRole("slider"), { target: { value: "2" } });
    expect(onChange).toHaveBeenLastCalledWith(undefined);
  });

  it("shows 'latest' label when at latest position", () => {
    render(<AsOfSlider vintages={["2026-06-02T00:00:00Z"]} onChange={vi.fn()} />);
    expect(screen.getByText(/latest/i)).toBeInTheDocument();
  });

  it("renders nothing special when no vintages", () => {
    const onChange = vi.fn();
    render(<AsOfSlider vintages={[]} onChange={onChange} />);
    // Only one stop (latest), no slider needed — or slider with just the latest stop
    expect(screen.getByText(/latest/i)).toBeInTheDocument();
  });
});
