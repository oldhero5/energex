"use client";

import { useState } from "react";
import type { CatalogLibrary } from "@/lib/api";

interface Catalog {
  libraries: CatalogLibrary[];
}

interface Props {
  catalog: Catalog;
  selectedLibrary?: string | null;
  selectedSymbol?: string | null;
  onSelect: (library: string, symbol: string) => void;
}

function FreshnessDot({ latestValidTime }: { latestValidTime: string | null }) {
  if (!latestValidTime) return <span className="h-1.5 w-1.5 rounded-full bg-faint shrink-0" />;
  const age = (Date.now() - new Date(latestValidTime).getTime()) / 86_400_000;
  const color = age <= 1 ? "bg-ok" : age <= 3 ? "bg-warn" : "bg-fail";
  return <span className={`h-1.5 w-1.5 rounded-full ${color} shrink-0`} />;
}

export function CatalogTree({ catalog, selectedLibrary, selectedSymbol, onSelect }: Props) {
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(catalog.libraries.map((l) => [l.name, true]))
  );

  return (
    <div className="space-y-0.5">
      {catalog.libraries.map((lib) => (
        <div key={lib.name}>
          <button
            onClick={() => setOpen((s) => ({ ...s, [lib.name]: !s[lib.name] }))}
            className="flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-xs font-medium text-muted hover:text-fg transition-colors"
          >
            <span className="num select-none">{open[lib.name] ? "▾" : "▸"}</span>
            <span className="truncate">{lib.name}</span>
            {lib.unreadable > 0 && (
              <span className="ml-auto num text-fail text-[10px]">!{lib.unreadable}</span>
            )}
          </button>
          {open[lib.name] && (
            <ul className="ml-3 border-l border-line-soft">
              {lib.symbols.map((sym) => {
                const isSelected =
                  selectedLibrary === lib.name && selectedSymbol === sym.symbol;
                return (
                  <li key={sym.symbol}>
                    <button
                      onClick={() => onSelect(lib.name, sym.symbol)}
                      className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs transition-colors ${
                        isSelected
                          ? "bg-accent-tint text-accent"
                          : "text-fg-2 hover:text-fg"
                      }`}
                    >
                      <FreshnessDot latestValidTime={sym.latest_valid_time} />
                      <span className="truncate">{sym.symbol}</span>
                      <span className="ml-auto num text-faint text-[10px] shrink-0">
                        {sym.row_count.toLocaleString()}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}
