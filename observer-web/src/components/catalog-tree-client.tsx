"use client";

import { useRouter } from "next/navigation";
import { CatalogTree } from "@/components/catalog-tree";
import type { CatalogLibrary } from "@/lib/api";

interface Props {
  catalog: { libraries: CatalogLibrary[] };
  selectedLibrary: string | null;
  selectedSymbol: string | null;
}

export function CatalogTreeClient({ catalog, selectedLibrary, selectedSymbol }: Props) {
  const router = useRouter();

  function handleSelect(library: string, symbol: string) {
    router.push(`/catalog?library=${encodeURIComponent(library)}&symbol=${encodeURIComponent(symbol)}`);
  }

  return (
    <CatalogTree
      catalog={catalog}
      selectedLibrary={selectedLibrary}
      selectedSymbol={selectedSymbol}
      onSelect={handleSelect}
    />
  );
}
