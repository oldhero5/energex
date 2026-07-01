import type { CatalogSymbol, SchemaDescription, VintageRow } from "@/lib/api";
import { SymbolTabs } from "@/components/symbol-tabs";

interface Props {
  library: string;
  sym: CatalogSymbol;
  schema: SchemaDescription | null;
  vintages: VintageRow[];
  schemaError?: string | null;
  vintagesError?: string | null;
}

export function SymbolDetail({
  library,
  sym,
  schema,
  vintages,
  schemaError,
  vintagesError,
}: Props) {
  return (
    <div className="panel p-5 space-y-4">
      <div className="flex items-baseline gap-3">
        <h2 className="num text-base font-semibold text-fg">{sym.symbol}</h2>
        <span className="text-xs text-muted">{library}</span>
      </div>

      {(schemaError || vintagesError) && (
        <div className="rounded border border-fail/30 bg-fail/10 px-3 py-2 text-xs text-fail space-y-1">
          {schemaError && <p>Schema: {schemaError}</p>}
          {vintagesError && <p>Vintages: {vintagesError}</p>}
        </div>
      )}

      <SymbolTabs
        library={library}
        sym={sym}
        schema={schema}
        vintages={vintages}
      />
    </div>
  );
}
