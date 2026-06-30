const SECTIONS = [
  { id: "overview", label: "Overview", href: "/" },
  { id: "catalog", label: "Catalog", href: "/catalog" },
  { id: "map", label: "Map", href: "/map" },
  { id: "graph", label: "Graph", href: "/graph" },
  { id: "quality", label: "Quality", href: "/quality" },
  { id: "admin", label: "Admin", href: "/admin", role: "admin" as const },
];

export function NavRail({ role, active }: { role: string; active: string }) {
  return (
    <nav className="w-56 shrink-0 border-r border-line-soft bg-panel p-3">
      <div className="px-2 py-3 num text-accent text-sm tracking-wide">ENERGEX · OBSERVER</div>
      <ul className="mt-2 space-y-0.5">
        {SECTIONS.filter((s) => !s.role || s.role === role).map((s) => (
          <li key={s.id}>
            <a
              href={s.href}
              className={`block rounded-md px-3 py-2 text-sm ${
                active === s.id ? "bg-accent-tint text-accent" : "text-fg-2 hover:text-fg"
              }`}
            >
              {s.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
