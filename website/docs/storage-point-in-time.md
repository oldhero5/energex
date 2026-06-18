---
id: storage-point-in-time
title: Storage & Point-in-Time
sidebar_label: Storage & Point-in-Time
---

# Storage & Point-in-Time

The storage layer (`energex.core.storage`) is the crown jewel: a bitemporal store of
record built on ArcticDB-on-MinIO, with a per-symbol version index that makes
point-in-time reads correct and crash-safe.

## The canonical frame

Before any write, a frame is canonicalized:

- `valid_time` is required, converted to tz-aware UTC then stored tz-naive UTC (ArcticDB
  strips timezones on store), and used as a sorted, de-duplicated `DatetimeIndex` named
  `Datetime`.
- Provenance columns are stamped on: `as_of`, `source`, `source_url`, `fetched_at`, and
  `vintage_reconstructed`.

## Revision modes

Each symbol has exactly one revision mode (routed by `energex.core.symbology`):

### `degenerate` — `write_bars`

For never-revised streams (FRED spot, intraday bars). `write_bars` appends with
de-duplication on the UTC index:

- First write creates the symbol.
- If the new rows are strictly after the existing tail, it uses a fast `append`.
- Otherwise (sparse interior inserts) it reads, concatenates, de-duplicates keeping the
  last value, and rewrites.
- If nothing is new, it is an idempotent no-op.

It deliberately never calls `lib.update(date_range)` — that would delete bars omitted
from the window. There is no vintage index for degenerate symbols; `as_of` equals
`fetched_at`.

### `bitemporal_replace` — `commit_vintage`

For sources where each release is a *complete* as-known series (NOAA). Every commit is a
full versioned write at a new `as_of`.

### `bitemporal_merge` — `commit_vintage`

For sources that revise a window *inline* (EIA). Before writing, `commit_vintage` reads
the full as-known series committed **strictly before** this `as_of` (no future leak) and
merges the revision onto it: revisions overwrite by exact `valid_time`, and prior rows
absent from the new frame survive.

```python
def _merge_revisions(prior, frame):
    # Revisions overwrite by exact valid_time; prior rows absent from the frame survive.
    if prior is None or prior.empty:
        return frame
    kept = prior[~prior.index.isin(frame.index)]
    return pd.concat([kept, frame]).sort_index()
```

`commit_vintage` is **idempotent**: if a vintage with the same `as_of` already exists, it
returns the existing version and never re-mutates a live vintage (unless `force=True`).

## The version index is the commit point

Vintage addressing uses an append-only, per-symbol sidecar index. For symbol `SYM`, the
index lives at the ArcticDB symbol named `SYM__vintages` and records, per vintage:
`as_of`, the ArcticDB INTEGER `version`, `fetched_at`, and `vintage_reconstructed`.

The protocol is deliberately two-step:

1. Write the data to ArcticDB (returns an integer version).
2. **Append a row to the vintage index.** This append is the atomic **commit point**.

If the process crashes between the two steps, the data version exists but is not
referenced by the index — an **orphan**. All correctness-critical reads resolve against
the committed index only, so an orphan is invisible to readers and is later removed by
`reconcile_orphans` (see [Operations](./operations.md)).

A best-effort ArcticDB snapshot is also taken per commit purely for UI convenience;
correctness never depends on it.

## Reading: `read_as_of`

```python
# Latest committed vintage:
df = read_as_of(lib, symbol)

# As the series was known at a specific knowledge time:
df = read_as_of(lib, symbol, as_of="2026-05-15")

# Optionally constrained to a valid_time range:
df = read_as_of(lib, symbol, as_of="2026-05-15", date_range=(lo, hi))
```

Resolution rules:

- **Degenerate symbols** filter on knowledge time directly: rows where `fetched_at` is at
  or before the requested `as_of`.
- **Bitemporal symbols** re-read the vintage index on every call and select the vintage
  with the greatest `as_of` that is at or before the requested one. With no `as_of`, the
  latest committed vintage is used (never an orphan write version). If the requested
  `as_of` precedes the earliest vintage, the result is empty.

This is what makes a backtest honest: ask for `as_of` = your decision date, and you get
exactly what was knowable then.

## Curves

`read_curve(commodity, as_of)` assembles a forward curve by reading each contract symbol
(via `symbology.contracts_for`) at the requested knowledge time and concatenating the
per-contract frames in contract order.

## The honesty flag, end to end

`vintage_reconstructed` rides from the orchestration layer (which sets it based on how
old the partition is) through `commit_vintage` into both the data frame and the vintage
index. A reader can therefore tell, per vintage, whether it was a genuine forward capture
or a backfilled reconstruction of already-revised data — and treat the two differently in
a backtest.

See [Architecture](./architecture.md#the-bitemporal-model) for the conceptual model and
[Orchestration](./orchestration.md) for where `reconstructed` is decided.
