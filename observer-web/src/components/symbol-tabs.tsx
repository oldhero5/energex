"use client";

import { useState } from "react";
import type { CatalogSymbol, SchemaDescription, VintageRow } from "@/lib/api";

type Tab = "overview" | "schema" | "vintages" | "series" | "quality";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "schema", label: "Schema" },
  { id: "vintages", label: "Vintages" },
  { id: "series", label: "Series" },
  { id: "quality", label: "Quality" },
];

interface Props {
  library: string;
  sym: CatalogSymbol;
  schema: SchemaDescription | null;
  vintages: VintageRow[];
}

function OverviewTab({ library, sym }: { library: string; sym: CatalogSymbol }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Badge label="Library" value={library} mono={false} />
        <Badge label="Symbol" value={sym.symbol} mono />
        <Badge label="Schema" value={sym.schema_name ?? "—"} mono />
        <Badge label="Rows" value={sym.row_count.toLocaleString()} mono />
        {sym.vintage_count !== null && (
          <Badge label="Vintages" value={String(sym.vintage_count)} mono />
        )}
        {sym.reconstructed_pct !== null && (
          <Badge label="Reconstructed" value={`${sym.reconstructed_pct}%`} mono />
        )}
      </div>
      <div>
        <p className="text-xs text-muted mb-1">Latest valid time</p>
        <p className="num text-sm text-fg">
          {sym.latest_valid_time ?? <span className="text-faint">none</span>}
        </p>
      </div>
    </div>
  );
}

function Badge({ label, value, mono }: { label: string; value: string; mono: boolean }) {
  return (
    <div className="rounded border border-line-soft bg-elev px-3 py-2 space-y-0.5">
      <p className="text-[10px] text-muted uppercase tracking-wider">{label}</p>
      <p className={`text-sm text-fg truncate ${mono ? "num" : ""}`}>{value}</p>
    </div>
  );
}

function SchemaTab({ schema }: { schema: SchemaDescription | null }) {
  if (!schema || !schema.schema_name) {
    return <p className="text-sm text-muted">No schema registered for this symbol.</p>;
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted">Schema</span>
        <span className="num text-xs text-accent">{schema.schema_name}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-line-soft">
              <th className="py-1.5 pr-4 text-left text-muted font-medium">Column</th>
              <th className="py-1.5 pr-4 text-left text-muted font-medium">Dtype</th>
              <th className="py-1.5 pr-4 text-left text-muted font-medium">Nullable</th>
              <th className="py-1.5 text-left text-muted font-medium">Checks</th>
            </tr>
          </thead>
          <tbody>
            {schema.columns.map((col) => (
              <tr key={col.name} className="border-b border-line-soft/40 hover:bg-elev/50">
                <td className="py-1.5 pr-4 num text-fg">{col.name}</td>
                <td className="py-1.5 pr-4 num text-fg-2">{col.dtype}</td>
                <td className="py-1.5 pr-4">
                  <span className={col.nullable ? "text-muted" : "text-ok"}>
                    {col.nullable ? "yes" : "no"}
                  </span>
                </td>
                <td className="py-1.5">
                  {col.checks.length > 0 ? (
                    <span className="num text-fg-2">{col.checks.join(", ")}</span>
                  ) : (
                    <span className="text-faint">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {schema.checks.length > 0 && (
        <div>
          <p className="text-xs text-muted mb-1">Table-level checks</p>
          <div className="flex flex-wrap gap-1">
            {schema.checks.map((c, i) => (
              <span key={i} className="num text-[10px] rounded px-1.5 py-0.5 bg-elev border border-line-soft text-fg-2">
                {c}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function VintagesTab({ vintages }: { vintages: VintageRow[] }) {
  if (vintages.length === 0) {
    return <p className="text-sm text-muted">No vintage sidecar for this symbol.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-line-soft">
            <th className="py-1.5 pr-4 text-left text-muted font-medium">As-of</th>
            <th className="py-1.5 pr-4 text-left text-muted font-medium">Version</th>
            <th className="py-1.5 pr-4 text-left text-muted font-medium">Fetched at</th>
            <th className="py-1.5 text-left text-muted font-medium">Reconstructed</th>
          </tr>
        </thead>
        <tbody>
          {vintages.map((v, i) => (
            <tr key={i} className="border-b border-line-soft/40 hover:bg-elev/50">
              <td className="py-1.5 pr-4 num text-fg">{v.as_of}</td>
              <td className="py-1.5 pr-4 num text-fg-2">{v.version}</td>
              <td className="py-1.5 pr-4 num text-fg-2">{v.fetched_at ?? "—"}</td>
              <td className="py-1.5">
                <span className={v.vintage_reconstructed ? "text-warn num" : "text-ok num"}>
                  {v.vintage_reconstructed ? "yes" : "no"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlaceholderTab({ label }: { label: string }) {
  return (
    <div className="rounded border border-line-soft/60 bg-elev/40 px-4 py-6 text-center">
      <p className="text-sm text-muted">{label} — loads in Task 7</p>
    </div>
  );
}

export function SymbolTabs({ library, sym, schema, vintages }: Props) {
  const [active, setActive] = useState<Tab>("overview");

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex gap-1 border-b border-line-soft pb-0">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setActive(t.id)}
            className={`px-3 py-1.5 text-xs font-medium transition-colors border-b-2 -mb-px ${
              active === t.id
                ? "border-accent text-accent"
                : "border-transparent text-muted hover:text-fg"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {active === "overview" && <OverviewTab library={library} sym={sym} />}
        {active === "schema" && <SchemaTab schema={schema} />}
        {active === "vintages" && <VintagesTab vintages={vintages} />}
        {active === "series" && <PlaceholderTab label="Series chart" />}
        {active === "quality" && <PlaceholderTab label="Quality report" />}
      </div>
    </div>
  );
}
