import { apiFetch } from "@/lib/api";
import type { CatalogLibrary, SchemaDescription, VintageRow } from "@/lib/api";
import { CatalogTreeClient } from "@/components/catalog-tree-client";
import { SymbolDetail } from "@/components/symbol-detail";

interface SearchParams {
  library?: string | string[];
  symbol?: string | string[];
}

function str(v: string | string[] | undefined): string | null {
  if (!v) return null;
  return Array.isArray(v) ? v[0] : v;
}

function isAuthError(msg: string): boolean {
  return /: 40[13]/.test(msg);
}

function ErrorBanner({ message }: { message: string }) {
  const authError = isAuthError(message);
  return (
    <div className="panel p-4">
      <p className="text-sm text-muted">
        {authError
          ? "Couldn't load data — you may not have access. Try signing in again."
          : "Couldn't load data — confirm observer-api is running and that you're signed in with access."}
      </p>
    </div>
  );
}

export default async function CatalogPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const selectedLibrary = str(sp.library);
  const selectedSymbol = str(sp.symbol);

  // Always fetch catalog
  let catalogResult: { libraries: CatalogLibrary[] } | { error: string } | null = null;
  try {
    catalogResult = await apiFetch<{ libraries: CatalogLibrary[] }>("/catalog");
  } catch (err) {
    console.error("[CatalogPage] catalog fetch failed:", err);
    catalogResult = { error: err instanceof Error ? err.message : String(err) };
  }

  const catalogError = catalogResult == null || "error" in catalogResult;
  const libraries =
    !catalogError && catalogResult !== null && "libraries" in catalogResult
      ? catalogResult.libraries
      : [];

  // Find selected symbol metadata from catalog (no extra fetch needed for overview data)
  const selectedLib = selectedLibrary
    ? libraries.find((l) => l.name === selectedLibrary)
    : null;
  const selectedSym = selectedLib && selectedSymbol
    ? selectedLib.symbols.find((s) => s.symbol === selectedSymbol)
    : null;

  // Fetch schema + vintages if a symbol is selected
  let schema: SchemaDescription | null = null;
  let schemaError: string | null = null;
  let vintages: VintageRow[] = [];
  let vintagesError: string | null = null;

  if (selectedLibrary && selectedSymbol) {
    const base = `/symbol/${selectedLibrary}/${selectedSymbol}`;

    const [schemaResult, vintagesResult] = await Promise.allSettled([
      apiFetch<{ schema_name: string | null; columns: SchemaDescription["columns"]; checks: string[] }>(
        `${base}/schema`
      ),
      apiFetch<{ library: string; symbol: string; vintages: VintageRow[] }>(
        `${base}/vintages`
      ),
    ]);

    if (schemaResult.status === "fulfilled") {
      schema = schemaResult.value;
    } else {
      console.error("[CatalogPage] schema fetch failed:", schemaResult.reason);
      schemaError = schemaResult.reason instanceof Error
        ? schemaResult.reason.message
        : String(schemaResult.reason);
    }

    if (vintagesResult.status === "fulfilled") {
      vintages = vintagesResult.value.vintages;
    } else {
      console.error("[CatalogPage] vintages fetch failed:", vintagesResult.reason);
      vintagesError = vintagesResult.reason instanceof Error
        ? vintagesResult.reason.message
        : String(vintagesResult.reason);
    }
  }

  return (
    <div className="flex h-full gap-4">
      {/* Left pane: tree */}
      <aside className="w-60 shrink-0 overflow-y-auto panel p-2">
        <p className="px-2 py-1.5 text-xs font-medium text-muted uppercase tracking-wider">
          Catalog
        </p>
        {catalogError ? (
          <ErrorBanner
            message={catalogResult != null && "error" in catalogResult ? catalogResult.error : "unavailable"}
          />
        ) : (
          <CatalogTreeClient
            catalog={{ libraries }}
            selectedLibrary={selectedLibrary}
            selectedSymbol={selectedSymbol}
          />
        )}
      </aside>

      {/* Right pane: detail */}
      <div className="flex-1 overflow-y-auto min-w-0">
        {selectedSym && selectedLibrary ? (
          <SymbolDetail
            library={selectedLibrary}
            sym={selectedSym}
            schema={schema}
            vintages={vintages}
            schemaError={schemaError}
            vintagesError={vintagesError}
          />
        ) : (
          <div className="panel p-6 text-sm text-muted">
            {selectedLibrary && selectedSymbol && !selectedSym
              ? `Symbol "${selectedSymbol}" not found in library "${selectedLibrary}".`
              : "Select a symbol from the tree to view details."}
          </div>
        )}
      </div>
    </div>
  );
}
