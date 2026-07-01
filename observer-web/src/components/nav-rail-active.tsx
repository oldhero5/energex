"use client";

import { usePathname } from "next/navigation";
import { NavRail } from "@/components/nav-rail";

const PATH_TO_SECTION: Record<string, string> = {
  "/": "overview",
  "/catalog": "catalog",
  "/map": "map",
  "/graph": "graph",
  "/quality": "quality",
  "/admin": "admin",
};

function sectionFromPath(pathname: string): string {
  // exact match first, then prefix
  if (PATH_TO_SECTION[pathname]) return PATH_TO_SECTION[pathname];
  for (const [prefix, section] of Object.entries(PATH_TO_SECTION)) {
    if (prefix !== "/" && pathname.startsWith(prefix)) return section;
  }
  return "overview";
}

export function NavRailActive({ role }: { role: string }) {
  const pathname = usePathname();
  return <NavRail role={role} active={sectionFromPath(pathname)} />;
}
