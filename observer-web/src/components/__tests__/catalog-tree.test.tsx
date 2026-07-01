import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CatalogTree } from "../catalog-tree";

const cat = {
  libraries: [
    {
      name: "power.load",
      mode: "bitemporal_merge",
      symbols: [
        {
          symbol: "erco",
          row_count: 1,
          latest_valid_time: null,
          vintage_count: 1,
          reconstructed_pct: 0,
          schema_name: "ERCOT_LOAD",
        },
      ],
      unreadable: 0,
    },
  ],
};

describe("CatalogTree", () => {
  it("renders libraries and symbols and fires onSelect", () => {
    const onSelect = vi.fn();
    render(<CatalogTree catalog={cat} onSelect={onSelect} />);
    expect(screen.getByText("power.load")).toBeInTheDocument();
    fireEvent.click(screen.getByText("erco"));
    expect(onSelect).toHaveBeenCalledWith("power.load", "erco");
  });
});
