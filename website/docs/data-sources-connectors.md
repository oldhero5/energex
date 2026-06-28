---
id: data-sources-connectors
title: Data Sources & Connectors
sidebar_label: Data Sources & Connectors
---

# Data Sources & Connectors

Energex is focused on **power markets**, with weather and gas/oil fundamentals as
supporting context. Each source is ingested through a dedicated connector in
`energex.core.connectors`. A connector does exactly one thing: pull a window from a source
and return a normalized `FetchResult`. It knows nothing about storage, the quality gate, or
Dagster — that wiring lives in [Orchestration](./orchestration.md). The connector layer is
framework- **and** storage-agnostic and must never import `arcticdb`.

## Power sources

These are the primary feeds. EIA-930 is the always-on backbone (every US balancing
authority); ERCOT adds nodal Texas price and load detail.

| Source | Connector class | ArcticDB library | Cadence | Revision mode |
| --- | --- | --- | --- | --- |
| **EIA-930** — hourly demand / day-ahead forecast / net generation / interchange (all BAs) | `Eia930RegionConnector` | `power.demand`, `power.demand_forecast`, `power.generation`, `power.interchange` | Hourly | `degenerate` |
| **EIA-930** — hourly net generation by fuel type (all BAs) | `Eia930FuelConnector` | `power.generation_by_fuel` | Hourly | `degenerate` |
| **ERCOT** — real-time (15-min) settlement-point prices, hubs + load zones | `ErcotRtSppConnector` | `power.lmp` | Intraday (hourly capture) | `bitemporal_merge` |
| **ERCOT** — day-ahead-market hourly settlement-point prices | `ErcotDamSppConnector` | `power.dalmp` | Daily (next-day curve) | `bitemporal_merge` |
| **ERCOT** — ERCOT-wide actual system load | `ErcotLoadConnector` | `power.load` | Intraday (hourly capture) | `bitemporal_merge` |

EIA-930 needs only the existing `EIA_API_KEY`. ERCOT authenticates via Azure AD B2C ROPC
(`ERCOT_USERNAME` / `ERCOT_PASSWORD` plus an APIM subscription key in
`ERCOT_API_KEY_PRIMARY`); absent credentials the ERCOT connectors fail fast with a clear
`ConfigurationError`.

### EIA-930 hourly grid monitor

The EIA-930 Hourly Electric Grid Monitor is the core power feed, served by two EIA v2 routes
for **every US balancing authority** (~65–73 BAs — the `respondent` facet is omitted, so all
BAs come back):

- `electricity/rto/region-data` — demand (`D`), day-ahead forecast (`DF`), net generation
  (`NG`), and total interchange (`TI`) → instruments `EIA930.{D,DF,NG,TI}.<BA>`, routed to
  `power.demand` / `power.demand_forecast` / `power.generation` / `power.interchange` by
  `Eia930RegionConnector`.
- `electricity/rto/fuel-type-data` — net generation by fuel type →
  `EIA930.GEN_FUEL.<BA>` (carrying a `fuel_type` column), routed to
  `power.generation_by_fuel` by `Eia930FuelConnector`.

The symbol is the BA code, lowercased (e.g. `erco`, `ciso`). EIA revises these hourly series
inline, so the assets write `degenerate` (append-with-dedup, latest-wins): a re-pull of a
recent window simply overwrites changed values. `valid_time` is the hourly `period` at UTC;
`value` is the MWh reading (signed for interchange, null where EIA has a gap).
`complete_over_range` is `False`. The `api_key` is read from `core.config`, never hardcoded,
and the provenance URL redacts it.

Because ERCOT fuel mix is **not** on ERCOT's public API, ERCOT fuel mix is covered here by
`EIA930.GEN_FUEL.ERCO`.

### ERCOT settlement-point prices and load

ERCOT's public API authenticates via Azure AD B2C ROPC (username + password + a fixed public
`client_id`) to mint an ID token, then serves report endpoints under
`https://api.ercot.com/api/public-reports` gated by the APIM subscription key. Responses use
an array-of-arrays `data` body with a separate `fields` schema and a `_meta` pagination
envelope. All ERCOT timestamps are Central Prevailing Time (`America/Chicago`), hour-ending,
and are converted to tz-aware UTC — DST-correct, including the repeated fall-back hour. Three
connectors are wired:

- **`ErcotRtSppConnector`** — real-time 15-min settlement-point prices (report
  `np6-905-cd/spp_node_zone_hub`) → `ERCOT.SPP.<sp>` → `power.lmp`.
- **`ErcotDamSppConnector`** — day-ahead-market hourly settlement-point prices (report
  `np4-190-cd/dam_stlmnt_pnt_prices`) → `ERCOT.DASPP.<sp>` → `power.dalmp`.
- **`ErcotLoadConnector`** — ERCOT-wide actual system load (report
  `np6-345-cd/act_sys_load_by_wzn`, the `total` column) → the single instrument
  `ERCOT.LOAD.ERCOT` → `power.load`.

Only the **13 canonical tradeable settlement points** are ingested — the 5 trading hubs
(`HB_HOUSTON`, `HB_NORTH`, `HB_PAN`, `HB_SOUTH`, `HB_WEST`) and 8 load zones (`LZ_AEN`,
`LZ_CPS`, `LZ_HOUSTON`, `LZ_LCRA`, `LZ_NORTH`, `LZ_RAYBN`, `LZ_SOUTH`, `LZ_WEST`); resource
nodes are dropped. RT/DAM prices and system load can be restated, so all three assets commit
`bitemporal_merge`. The connectors page through the envelope and follow no redirects, so a
30x can never move the credentialed request off-host. Each fetch returns
`complete_over_range=False` (a window, not the full as-known series).

## Supporting sources (deprioritized)

Oil & gas and weather remain ingested but are no longer the focus:

| Source | Connector class | ArcticDB library | Cadence | Revision mode |
| --- | --- | --- | --- | --- |
| **FRED** — WTI / Brent / Henry Hub spot | `FredConnector` | `prices.spot` | Daily (weekdays) | `degenerate` |
| **EIA v2** — Lower-48 working gas in storage | `EiaGasStorageConnector` | `fundamentals.eia` | Weekly (Thu) | `bitemporal_merge` |
| **EIA v2** — U.S. crude stocks ex-SPR | `EiaPetroleumStatusConnector` | `fundamentals.eia` | Weekly (Wed) | `bitemporal_merge` |
| **NOAA nClimDiv** — HDD/CDD by region | `NOAANClimDivConnector` | `weather` | Monthly | `bitemporal_replace` |
| **yfinance** — front-month CL/BZ/NG intraday | `YFinanceIntradayConnector` | `prices.intraday` | Manual (dev only) | `degenerate` |

### FRED benchmark spot

The St. Louis Fed FRED API serves daily benchmark spot prices with a few-business-day
publication lag. Three series are pulled (codes verified live, never invented):

- `DCOILWTICO` — WTI crude, Cushing OK ($/bbl) → `FRED.WTI.SPOT`
- `DCOILBRENTEU` — Brent crude, Europe ($/bbl) → `FRED.BRENT.SPOT`
- `DHHNGSP` — Henry Hub natural gas ($/MMBtu) → `FRED.HENRYHUB.SPOT`

These are final daily values (FRED does not vintage them on this endpoint), so the stream is
`degenerate`: the asset appends with de-duplication and `as_of` = `fetched_at`. FRED emits
missing observations (holidays/gaps) as the string `"."`; those are dropped.
`complete_over_range` is `False`.

### EIA fundamentals

EIA's open-data v2 API serves weekly fundamentals. Two routes are wired, with series codes
pulled live from EIA's facet endpoints (never invented):

- `natural-gas/stor/wkly` — Lower-48 working gas in underground storage (Bcf;
  facets `duoarea=R48`, `process=SWO`, `product=EPG0`) → instrument
  `EIA.NG.STORAGE.LOWER48`.
- `petroleum/stoc/wstk` — U.S. crude oil ending stocks **excluding SPR** (thousand barrels;
  facets `product=EPC0`, `process=SAX`, `duoarea=NUS`) → instrument `EIA.PET.CRUDE.STOCKS`.

EIA has **no vintage parameter** and revises prior weeks **inline**. So every fetch widens
its window back by a revision lookback (`REVISION_LOOKBACK`, six weeks) to re-carry EIA's
revisions, and the asset commits `bitemporal_merge`. `complete_over_range` is `False` — a
revision window is not the full as-known series.

### NOAA degree days

NOAA's nClimDiv monthly fixed-width files (no API token needed) provide combined HDD+CDD per
region. The connector reads the live directory listing and selects the newest dated
`climdiv-hddcst-*` / `climdiv-cddcst-*` file (never a hardcoded version), then emits one
`NOAA.HDD.<region>` instrument per region carrying both `hdd` and `cdd` columns. Coverage is
the contiguous-US national aggregate (`CONUS`), the nine NCEI climate regions, and Texas. The
whole file is the full as-known series, so `complete_over_range=True` and the asset commits
`bitemporal_replace`.

### yfinance intraday (dev only)

The yfinance connector fetches front-month CL/BZ/NG 1-minute OHLCV bars
(`CME.{CL,BZ,NG}.FRONT` → `prices.intraday`). It is the original proof-of-pipeline vertical
slice and is **not scheduled**: Yahoo frequently blocks programmatic access, so a schedule
would only fire failing runs. Run it manually from the Dagster UI when you want intraday data
in dev.

## The Connector protocol

Every connector implements one small contract from `energex.core.connectors.base`:

```python
@dataclass(frozen=True)
class FetchResult:
    frame: pd.DataFrame          # instrument_id + tz-aware-UTC valid_time + value columns
    source: str
    fetched_at: datetime         # tz-aware UTC knowledge time
    source_url: str
    complete_over_range: bool    # True iff frame is the full as-known series for its span


@runtime_checkable
class Connector(Protocol):
    source: str
    def fetch(self, window_start: date, window_end: date) -> FetchResult: ...
```

`complete_over_range` is the merge-vs-replace signal: it is `True` only when the frame is the
full as-known series for its `valid_time` span (a whole-file replace source like NOAA), and
`False` for an inline-revision window (EIA fundamentals, ERCOT) or a continuous degenerate
stream (EIA-930, FRED).

## How to add a new connector

1. **Pick the instrument IDs and route them.** For a fixed, small set of series, add entries
   to the `_TABLE` in `energex.core.symbology`, mapping each `instrument_id` to its
   `(library, symbol, revision_mode)`. The revision mode must be consistent with the
   library's mode in `LIBRARY_MODE`.

   ```python
   # energex/core/symbology.py
   "EIA.NG.STORAGE.LOWER48": ("fundamentals.eia", "ng_storage_lower48", "bitemporal_merge"),
   ```

   For high-cardinality namespaces (e.g. the ~65–73 EIA-930 balancing authorities, or the
   ERCOT settlement points) enumerating every symbol is brittle. Instead add a prefix to
   `_POWER_PREFIX` and let `resolve()` route by rule (`EIA930.<SERIES>.<BA>` →
   library + lowercased BA symbol). Because the bare symbol then drops its routing prefix,
   storage takes the mode explicitly via `mode_for_library()` rather than the symbol-based
   reverse lookup.

2. **Define a pandera schema** for the connector's output frame in `energex.core.schemas`
   (column names, dtypes, nullability, value bands, uniqueness, a row-count floor, and a
   release-calendar-aware freshness bound). The quality gate (`core.quality.validate`)
   validates against this before any write and raises `QualityGateError` on failure.

3. **Implement the connector** in `energex/core/connectors/`. Follow the existing ones
   (`fred.py` is the simplest): fetch over the requested window, normalize to columns
   `instrument_id`, tz-aware-UTC `valid_time`, and your value column(s), and return a
   `FetchResult` with accurate provenance and `complete_over_range`. Read API keys from
   `energex.core.config` (never hardcode; redact them from `source_url`), and wrap network
   calls in tenacity retries over `httpx`. **Do not import a framework or `arcticdb`.**

4. **Wire a Dagster asset** in `energex.orchestration.assets`: fetch → `quality.validate`
   → `storage.write_bars` (degenerate) or `storage.commit_vintage` (bitemporal), grouping
   the frame by `instrument_id` and resolving each via `symbology.resolve`. Add an asset
   check in `checks.py` that re-runs the same `validate(...)` against the read-back.

5. **Add a partition + schedule** in `partitions.py` and `schedules.py` if the source has a
   regular release cadence.

6. **Test it.** Add a connector test (see `tests/test_connector_*.py`) that mocks the HTTP
   layer with `respx` and asserts the shape, provenance, and `complete_over_range` of the
   `FetchResult`.

See [Orchestration](./orchestration.md) for how assets, checks, and schedules fit together,
and [Storage & Point-in-Time](./storage-point-in-time.md) for the commit functions and the
bitemporal model. The downstream contract for reading any of this back is the
[S2 read API](./frontend-integration.md).
