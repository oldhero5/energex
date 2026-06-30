import { apiFetch } from "@/lib/api";

interface Library {
  name: string;
  symbols: number;
  rows: number;
  unreadable: number;
}

async function getCatalog(): Promise<{ libraries: Library[] } | { error: string } | null> {
  try {
    return await apiFetch<{ libraries: Library[] }>("/catalog");
  } catch (err) {
    console.error("[OverviewPage] getCatalog failed:", err);
    const msg = err instanceof Error ? err.message : String(err);
    return { error: msg };
  }
}

export default async function OverviewPage() {
  const data = await getCatalog();

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-fg">Overview</h1>
      <div className="panel p-4">
        <h2 className="mb-3 text-sm font-medium text-muted">Data Libraries</h2>
        {data == null || "error" in data ? (
          <p className="text-sm text-muted">
            {data != null && "error" in data && /: 40[13]/.test(data.error)
              ? "Couldn't load the catalog — you may not have access. Try signing in again."
              : "Couldn't load the catalog — confirm observer-api is running and that you're signed in with access."}
          </p>
        ) : data.libraries.length === 0 ? (
          <p className="text-sm text-muted">No libraries found.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="pb-2 font-medium">Library</th>
                <th className="pb-2 font-medium num">Symbols</th>
                <th className="pb-2 font-medium num">Rows</th>
                <th className="pb-2 font-medium num">Unreadable</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-soft">
              {data.libraries.map((lib) => (
                <tr key={lib.name}>
                  <td className="py-2 text-fg">{lib.name}</td>
                  <td className="py-2 num text-fg-2">{lib.symbols}</td>
                  <td className="py-2 num text-fg-2">{lib.rows.toLocaleString()}</td>
                  <td className="py-2 num text-muted">{lib.unreadable}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
