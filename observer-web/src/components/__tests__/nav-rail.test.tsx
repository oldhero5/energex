import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { NavRail } from "../nav-rail";

describe("NavRail", () => {
  it("shows core sections to a viewer but hides Admin", () => {
    render(<NavRail role="viewer" active="overview" />);
    for (const s of ["Overview", "Catalog", "Map", "Graph", "Quality"])
      expect(screen.getByText(s)).toBeInTheDocument();
    expect(screen.queryByText("Admin")).toBeNull();
  });
  it("shows Admin to an admin", () => {
    render(<NavRail role="admin" active="overview" />);
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });
});
