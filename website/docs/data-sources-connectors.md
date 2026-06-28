---
id: data-sources-connectors
title: Data Sources & Connectors
sidebar_label: Data Sources & Connectors
---

# Data Sources & Connectors

Energex is focused on **power markets**, with weather and gas/oil fundamentals as
supporting context. Each source is ingested through a dedicated connector in
`energex.core.connectors`. A connector is responsible for one thing: pull a window from a
source and return a normalized `FetchResult`. It knows nothing about storage or Dagster.

## Power sources

| Source | Connector class | ArcticDB library | Cadence | Revision mode |
| --- | --- | --- | --- | --- |
| **EIA-930** — hourly demand / day-ahead forecast / net generation / interchange (all BAs) | `Eia930RegionConnector` | `power.demand`, `power.demand_forecast`, `power.generation`, `power.interchange` | Hourly | `degenerate` |
| **EIA-930** — hourly net generation by fuel type (all BAs) | `Eia930FuelConnector` | `power.generation_by_fuel` | Hourly | `degenerate` |
| **ERCOT** — real-time (15-min) settlement point prices, hubs + load zones | `ErcotRtSppConnector` | `power.lmp` | 15-min (hourly refresh) | `bitemporal_merge` |
| **ERCOT** — day-ahead-market hourly settlement point prices | `ErcotDamSppConnector` | `power.dalmp` | Daily | `bitemporal_merge` |
| **ERCOT** — ERCOT-wide actual system load | `ErcotLoadConnector` | `power.load` | Hourly | `bitemporal_merge` |

ERCOT authenticates via Azure AD B2C ROPC (`ERCOT_USERNAME` / `ERCOT_PASSWORD` plus an APIM
subscription key in `ERCOT_API_KEY_PRIMARY`) and serves nodal reports under
`api.ercot.com/api/public-reports`. The connectors mint an ID token, page through the
`data` / `fields` / `_meta` envelope, and convert Central Prevailing time to UTC. Only the
canonical tradeable settlement points (5 trading hubs + 8 load zones) are ingested. Fuel
mix is **not** on the public-reports API — ERCOT fuel mix is served by EIA-930
(`EIA930.GEN_FUEL.ERCO`). Absent credentials, the connectors fail fast with a clear message.
EIA-930 needs only the existing `EIA_API_KEY`.

## Supporting sources (deprioritized)

Oil & gas and weather remain ingested but are no longer the focus:

| Source | Connector class | ArcticDB library | Cadence | Revision mode |
| --- | --- | --- | --- | --- |
| **NOAA nClimDiv** — HDD/CDD by region | `NOAANClimDivConnector` | `weather` | Monthly | `bitemporal_replace` |
| **FRED** — WTI / Brent / Henry Hub spot | `FredConnector` | `prices.spot` | Daily (weekdays) | `degenerate` |
| **EIA v2** — Lower-48 working gas in storage | `EiaGasStorageConnector` | `fundamentals.eia` | Weekly (Thu) | `bitemporal_merge` |
| **EIA v2** — U.S. crude stocks ex-SPR | `EiaPetroleumStatusConnector` | `fundamentals.eia` | Weekly (Wed) | `bitemporal_merge` |
| **yfinance** — front-month CL/BZ/NG intraday | `YFinanceIntradayConnector` | `prices.intraday` | Manual (dev only) | `degenerate` |

### EIA-930 hourly grid monitor

EIA's Hourly Electric Grid Monitor (the EIA-930 dataset) is the core power feed, served by
two EIA v2 routes for **every US balancing authority** (~60–70 BAs):

- `electricity/rto/region-data` — demand (`D`), day-ahead forecast (`DF`), net generation
  (`NG`), and total interchange (`TI`) → instruments `EIA930.{D,DF,NG,TI}.<BA>`.
- `electricity/rto/fuel-type-data` — net generation by fuel type →
  `EIA930.GEN_FUEL.<BA>` (carrying a `fuel_type` column).

Each series is its own library; the symbol is the BA code (e.g. `erco`, `ciso`). The data
is hourly and finalizes within about a day, so the asset writes `degenerate`
(append-with-dedup, latest-wins) over a short re-pull window. A `~3-year` backfill seeds
history; an hourly schedule keeps it current.

### ERCOT nodal

ERCOT's public API covers real-time (NP6-905-CD, 15-min SCED) and day-ahead (NP4-190-CD,
hourly) settlement point prices → `power.lmp` / `power.dalmp`, and actual system load
(NP6-345-CD) → `power.load` (one symbol per settlement point; load uses the single
`ercot` symbol). Prices and load can be restated, so the assets commit `bitemporal_merge`.
The connectors are unit-tested offline against the real response envelope and run live once
the ERCOT credentials are present.

### EIA fundamentals

EIA's open-data v2 API serves weekly fundamentals. Two routes are wired, with series
codes pulled live from EIA's facet endpoints (never invented):

- `natural-gas/stor/wkly` — Lower-48 working gas in underground storage (Bcf) →
  instrument `EIA.NG.STORAGE.LOWER48`.
- `petroleum/stoc/wstk` — U.S. crude oil ending stocks **excluding SPR** (thousand
  barrels) → instrument `EIA.PET.CRUDE.STOCKS`.

EIA has **no vintage parameter** and revises prior weeks **inline**. So every fetch
widens its window back by a revision lookback (at least five weeks) to re-carry EIA's
revisions, and the asset commits `bitemporal_merge`. `complete_over_range` is `False` — a
revision window is not the full as-known series.

### NOAA degree days

NOAA's nClimDiv monthly files provide combined HDD+CDD per region: the contiguous-US
national aggregate, the nine NCEI climate regions, and Texas. The whole file is reissued
each month, so each release is a complete as-known series and the asset commits
`bitemporal_replace`. The flat files are public and need no token.

### FRED benchmark spot

The St. Louis Fed FRED API serves daily benchmark spot prices with a few-business-day
publication lag. Three series are pulled:

- `DCOILWTICO` — WTI crude, Cushing OK ($/bbl) → `FRED.WTI.SPOT`
- `DCOILBRENTEU` — Brent crude, Europe ($/bbl) → `FRED.BRENT.SPOT`
- `DHHNGSP` — Henry Hub natural gas ($/MMBtu) → `FRED.HENRYHUB.SPOT`

These are final daily values (FRED does not vintage them on this endpoint), so the stream
is `degenerate`: the asset appends with de-duplication and `as_of` = `fetched_at`. FRED
emits missing observations (holidays/gaps) as the string `"."`; those are dropped.

### yfinance intraday (dev only)

The yfinance connector fetches front-month CL/BZ/NG 1-minute OHLCV bars. It is the S1
proof-of-pipeline vertical slice and is **not scheduled**: Yahoo frequently blocks
programmatic access, so a schedule would only fire failing runs. Run it manually from the
Dagster UI when you want intraday data in dev.

## The Connector protocol

Every connector implements one small contract from
`energex.core.connectors.base`:

```python
@dataclass(frozen=True)
class FetchResult:
    frame: pd.DataFrame          # instrument_id + tz-aware-UTC valid_time + value columns
    source: str
    fetched_at: datetime         # tz-aware UTC knowledge time
    source_url: str
    complete_over_range: bool     # True iff frame is the full as-known series for its span


@runtime_checkable
class Connector(Protocol):
    source: str
    def fetch(self, window_start: date, window_end: date) -> FetchResult: ...
```

`complete_over_range` is the merge-vs-replace signal: it is `True` only when the frame is
the full as-known series for its `valid_time` span (a whole-file replace source), and
`False` for an inline-revision window or a continuous degenerate stream.

This module is framework- **and** storage-agnostic — it must not import `arcticdb`.

## How to add a new connector

1. **Pick the instrument IDs and route them.** Add entries to the `_TABLE` in
   `energex.core.symbology`, mapping each `instrument_id` to its `(library, symbol,
   revision_mode)`. The revision mode must be consistent with the library's mode in
   `LIBRARY_MODE`.

   ```python
   # energex/core/symbology.py
   "EIA.NG.STORAGE.LOWER48": ("fundamentals.eia", "ng_storage_lower48", "bitemporal_merge"),
   ```

   For high-cardinality namespaces (e.g. the ~60–70 EIA-930 balancing authorities)
   enumerating every symbol is brittle. Instead add a prefix to `_POWER_PREFIX` and let
   `resolve()` route by rule (`EIA930.<SERIES>.<BA>` → library + lowercased BA symbol).
   Because the bare symbol then drops its routing prefix, storage takes the mode
   explicitly via `mode_for_library()` rather than the symbol-based reverse lookup.

2. **Define a pandera schema** for the connector's output frame in
   `energex.core.schemas` (column names, dtypes, nullability, ranges). The quality gate
   validates against this before any write.

3. **Implement the connector** in `energex/core/connectors/`. Follow the existing ones
   (`fred.py` is the simplest): fetch over the requested window, normalize to columns
   `instrument_id`, tz-aware-UTC `valid_time`, and your value column(s), and return a
   `FetchResult` with accurate provenance and `complete_over_range`. Read API keys from
   `energex.core.config` (never hardcode), and wrap network calls in tenacity retries
   over `httpx`. **Do not import a framework.**

4. **Wire a Dagster asset** in `energex.orchestration.assets`: fetch → `quality.validate`
   → `storage.write_bars` (degenerate) or `storage.commit_vintage` (bitemporal),
   grouping the frame by `instrument_id` and resolving each via `symbology.resolve`. Add
   an asset check in `checks.py` that re-runs the same `validate(...)`.

5. **Add a partition + schedule** in `partitions.py` and `schedules.py` if the source has
   a regular release cadence.

6. **Test it.** Add a connector test (see `tests/test_connector_*.py`) that mocks the
   HTTP layer with `respx` and asserts the shape, provenance, and `complete_over_range`
   of the `FetchResult`.

See [Orchestration](./orchestration.md) for how assets, checks, and schedules fit
together, and [Storage & Point-in-Time](./storage-point-in-time.md) for the commit
functions.
