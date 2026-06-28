---
id: storage-point-in-time
title: Storage & Point-in-Time
sidebar_label: Storage & Point-in-Time
---

# Storage & Point-in-Time

The storage layer (`energex.core.storage`) is the crown jewel: a bitemporal store of
record built on ArcticDB-on-MinIO, with a per-symbol version index that makes
point-in-time reads correct and crash-safe. Every power series — EIA-930 demand,
forecast, generation, interchange, and net generation by fuel for ~65–73 balancing
authorities, plus ERCOT real-time / day-ahead SPP and system load — lands here, and so
do the supporting oil, gas, and weather series. The store records both **what** a value
was and **when** Energex learned it.

## Two clocks

Every row lives on two axes:

- **`valid_time`** — the period the row *describes* (the operating hour, the settlement
  interval, the release week). Required on every inbound frame; tz-aware UTC.
- **`as_of`** — the knowledge time, *when Energex learned* this value. Set by the
  orchestration layer per vintage.

`read_as_of(lib, symbol, as_of=...)` reconstructs what was known at a past knowledge time
and **never leaks the future**. This is what makes a backtest honest: ask for `as_of` =
your decision date, and you get exactly what was knowable then. See
[Architecture](./architecture.md) for the conceptual model and
[Orchestration](./orchestration.md) for where `as_of` and `reconstructed` are decided.

## The canonical frame

Before any write, `_canonicalize` normalizes a frame:

- `valid_time` is required (`StorageError` otherwise), parsed as UTC, then stored
  **tz-naive UTC** (ArcticDB strips timezones on store) as a sorted, de-duplicated
  `DatetimeIndex` named `Datetime` (keeping the last value per duplicate).
- Provenance columns are stamped on: `as_of`, `source`, `source_url`, `fetched_at`, and
  `vintage_reconstructed`.

```python
VINTAGE_COLS = ("as_of", "version", "fetched_at", "vintage_reconstructed")
```

## Revision modes

Each symbol has exactly one revision mode, routed by `energex.core.symbology` (the
rule-based `power.*` router, or the static reverse index for supporting series).

### `degenerate` — `write_bars`

For never-revised streams (FRED WTI/Brent/Henry Hub spot, EIA-930 region series, dev-only
intraday bars). `write_bars` appends with de-duplication on the UTC index:

- First write creates the symbol.
- If the new rows are strictly after the existing tail (`new.index.min() >
  existing.index.max()`), it uses a fast `lib.append`.
- Otherwise (sparse interior inserts) it reads, concatenates, de-duplicates keeping the
  last value, and rewrites.
- If nothing is new, it is an idempotent no-op.

It deliberately **never** calls `lib.update(date_range)` — that would delete bars omitted
from the window. There is no vintage index for degenerate symbols; `as_of` equals
`fetched_at`. Because `power.*` symbols are high-cardinality and not in the static reverse
index, the asset passes `mode` explicitly; `write_bars` refuses any non-degenerate symbol.

### `bitemporal_replace` — `commit_vintage`

For sources where each release is a *complete* as-known series (NOAA nClimDiv HDD/CDD).
Every commit is a full versioned write at a new `as_of`.

### `bitemporal_merge` — `commit_vintage`

For sources that revise a window *inline* — ERCOT real-time / day-ahead SPP and load, and
the EIA weekly fundamentals. Before writing, `commit_vintage` reads the full as-known
series committed **strictly before** this `as_of` (no future leak) and merges the revision
onto it: revisions overwrite by exact `valid_time`, and prior rows absent from the new
frame survive.

```python
def _merge_revisions(prior, frame):
    # Revisions overwrite by exact valid_time; prior rows absent from the frame survive.
    if prior is None or prior.empty:
        return frame
    kept = prior[~prior.index.isin(frame.index)]
    return pd.concat([kept, frame]).sort_index()
```

The prior series comes from `_read_full_series_before`, which selects the greatest
committed `as_of` **strictly less than** this one — so a merge can never fold in a future
revision.

## Idempotency: two layers

`commit_vintage` is idempotent on two distinct grounds, and either short-circuits the
write:

1. **as_of idempotency.** If a vintage with the same `as_of` already exists in the index,
   it returns the existing version and never re-mutates a live vintage (unless
   `force=True`).
2. **Content idempotency.** Even under a *new* `as_of`, if the canonical payload matches
   the latest committed vintage, the commit adds no knowledge and is skipped (the existing
   version is returned). `_same_payload` compares the index and all **non-provenance**
   columns — `as_of`, `source`, `source_url`, `fetched_at`, `vintage_reconstructed` are
   excluded, because an unchanged re-pull under a fresh `as_of` is not new knowledge.

Content idempotency is what keeps an hourly, full-history re-pull (the ERCOT case) from
writing a brand-new vintage every run; without it the store would grow unbounded.

## The version index is the commit point

Vintage addressing uses an append-only, per-symbol sidecar index. For symbol `SYM`, the
index lives at the ArcticDB symbol named `SYM__vintages` and records, per vintage:
`as_of`, the ArcticDB INTEGER `version`, `fetched_at`, and `vintage_reconstructed`.

The protocol is deliberately two-step:

1. Write the data to ArcticDB (returns an integer version).
2. **Append a row to the vintage index** (`_append_vintage_index`). This per-symbol write
   is the atomic **commit point**.

If the process crashes between the two steps, the data version exists but is not
referenced by the index — an **orphan**. All correctness-critical reads resolve against
the committed index only, so an orphan is invisible to readers and is later removed by
`reconcile_orphans` (see [Operations](./operations.md)).

A best-effort ArcticDB snapshot is also taken per commit (named
`{symbol}@{as_of}` at microsecond resolution) purely for UI convenience; correctness never
depends on it, and the call is wrapped so a snapshot failure cannot fail a commit.

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
  or before the requested `as_of` (never `valid_time`).
- **Bitemporal symbols** re-read the vintage index on *every* call and select the vintage
  with the greatest `as_of` that is at or before the requested one. With no `as_of`, the
  latest committed vintage is used (`_latest_committed_version`, never an orphan write
  version). If the requested `as_of` precedes the earliest vintage, the result is empty
  (an empty frame with the right columns).

This is the same point-in-time contract the [S2 read API](./frontend-integration.md)
exposes: every data endpoint accepts an optional `as_of`, defaulting to the latest
committed vintage.

## Curves

`read_curve(commodity, as_of)` assembles a forward curve by reading each contract symbol
(via `symbology.contracts_for`) at the requested knowledge time and concatenating the
per-contract frames in contract order. It is the engine behind the read API's `/curve`
endpoint.

## The honesty flag, end to end

`vintage_reconstructed` rides from the orchestration layer (which sets it based on how old
the partition is) through `commit_vintage` into both the data frame and the vintage index.
True point-in-time history accrues only going *forward*; rows backfilled for already-revised
periods are flagged `vintage_reconstructed=True`. A reader can therefore tell, per vintage,
whether it was a genuine forward capture or a backfilled reconstruction — and treat the two
differently in a backtest.

See [Data Sources & Connectors](./data-sources-connectors.md) for what each series carries,
and [Orchestration](./orchestration.md) for where `reconstructed` is decided.
