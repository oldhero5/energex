interface BrokenItem {
  library: string;
  symbol: string;
}

interface Props {
  items: BrokenItem[];
}

export function BrokenRail({ items }: Props) {
  return (
    <div className="panel p-4">
      <h2 className="mb-3 text-sm font-medium text-muted">Broken / Stale Data</h2>
      {items.length === 0 ? (
        <p className="text-sm text-ok">No broken data.</p>
      ) : (
        <ul className="space-y-1">
          {items.map((item, i) => (
            <li
              key={`${item.library}/${item.symbol}-${i}`}
              className="flex items-center gap-3 rounded-md bg-accent-tint px-3 py-1.5 text-sm"
            >
              <span className="h-2 w-2 shrink-0 rounded-full bg-fail" aria-hidden="true" />
              <span className="text-fg-2">{item.library}</span>
              <span className="text-fg font-medium">{item.symbol}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
