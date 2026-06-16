# Energex — Unified Platform Design (S1 foundation + S2–S4 program)

> **Status:** Approved design, pre-implementation.
> **Date:** 2026-06-16.
> **Scope:** A world-class rebuild of Energex as one coherent platform, decomposed into four
> sub-projects (S1–S4). **S1 (the unified data platform) is built first**; S2–S4 each get their own
> design→plan→build cycle afterward.
> **Relationship to `energex-ingestion-spec.md`:** that file is the original opinionated ingestion
> build spec. This document supersedes and corrects it where live API verification or the adversarial
> design review found problems (vintage addressing, ERCOT product, NOAA granularity, crash-safety,
> the pandas↔polars seam). Where they agree, the ingestion spec's invariants stand.

---

## 1. Program overview & decomposition

Energex becomes **one hexagonal platform**. A pure, framework-agnostic `energex.core` package
(**zero Dagster / FastAPI / LangGraph imports, CI-enforced**) owns every business contract. Three
swappable driver layers plug into that single core seam:

| Sub-project | Package | Role | Built |
|---|---|---|---|
| **S1 — Unified data platform** | `energex.orchestration` | The only package importing Dagster. Write-side: `fetch → validate → commit-vintage`. Assets, checks, partitions, schedules, backfills, GC/reconcile. | **First (this spec)** |
| **S2 — Analytics + serving** | `energex.service` | Read-mostly FastAPI over `core.storage.read_as_of` + reused analytics. `as_of` first-class on every endpoint. | After S1 phase 5 |
| **S3 — Agent** | `energex.agent` | LangGraph agent whose tools *are* the core read/analytics functions, each threading an explicit `as_of`. | After S2 |
| **S4 — Frontend** | dashboard | Consumes S2 JSON/Plotly + S3 chat; headline feature is an `as_of` time-travel slider that flags reconstructed vs true vintages. Dagster webserver (:3000) is the operator console, not the product UI. | After S2/S3 |

**Build philosophy:** re-architect & **reuse the good**. The repo has 122 passing tests and
methodologically-correct analytics (volatility, dated-futures, structured-output sentiment, charts,
FastAPI endpoints). These are preserved (analytics are storage-agnostic — they take a DataFrame in
their constructor) and migrated onto the unified architecture; only weak/legacy parts are rebuilt.
**No greenfield rewrite of working tested code.**

---

## 2. Locked decisions

1. **Stack:** Build the ingestion subsystem exactly as specified — Dagster + ArcticDB on MinIO/S3 +
   pandera gate + Neo4j entity graph. All five invariants hold (framework-agnostic core; bitemporal
   point-in-time correctness; fail-loud quality gate **before** every write; idempotent/backfillable;
   secrets-from-env only).
2. **Scope:** the whole platform (S1–S4). S1 first.
3. **Reuse:** re-architect & reuse the tested code; rebuild only weak/legacy parts.
4. **Futures unification:** migrate the existing yfinance→DuckDB→APScheduler futures-price ingestion
   onto the unified Dagster + ArcticDB architecture; retire the APScheduler/DuckDB island.
5. **Futures source (v1):** ship **yfinance as a clearly-labeled dev/research adapter** (degenerate
   intraday + dated). Dated-futures analytics are **exploratory-grade** in v1. Production CL/NG via
   Databento GLBX.MDP3 + Brent via ICE is a deferred paid R14 track that slots into the same
   `Connector` contract later.
6. **First ISO:** **ERCOT**, via the **Public REST API** (`api.ercot.com`, OAuth2 ROPC +
   `Ocp-Apim-Subscription-Key`), history floor **2023-12-11**. *(Not "Data Miner 2", which is PJM-only.)*
7. **Weather:** **monthly nClimDiv HDD/CDD** fixed-width files (true historical vintages via dated
   archive files). Daily GHCN-Daily degree-days deferred.
8. **Neo4j:** included, as **non-blocking phase 9**; symbology stays a static dict the graph merely
   references (numbers stay in Arctic; the graph answers what/who/connected).
9. **Vintage retention:** **keep all vintages forever** (full audit + deep point-in-time history),
   mitigated by separate volumes + disk alerting. Retention may be revisited if disk pressure appears.
10. **Deployment host:** the user's **always-on Mac Studio** (Tailscale `100.113.71.18`) — a
    non-laptop, non-sleeping host. Satisfies the always-on requirement; ERCOT US-egress confirmed by a
    startup geo-probe that fails loud.
11. **DataFrames:** new `core` is **pandas** (ArcticDB + pandera are pandas-first). Existing Polars
    analytics stay; all ArcticDB→analytics reads pass through one canonical `core.storage._to_polars`
    adapter.
12. **S3 agent authority:** defaults to **read-only**; Dagster-trigger authority is deferred to S3.

---

## 3. Target architecture (hexagonal)

```
                         ┌──────────────────────────── energex.core (pure, zero framework imports) ───────────────────────────┐
                         │ connectors/ (Connector Protocol + FetchResult)   storage.py (ArcticDB bitemporal + commit protocol) │
                         │ quality.py (pandera gate)   symbology.py (resolve + revision_mode)   llm.py   graph.py   _to_polars  │
                         └───────▲───────────────────────────────▲───────────────────────────────▲───────────────────────────┘
                                 │ write-side                     │ read-side                      │ read-side
                ┌────────────────┴─────────┐      ┌───────────────┴────────────┐      ┌───────────┴────────────┐
   S1          │ energex.orchestration     │  S2  │ energex.service (FastAPI)   │  S3  │ energex.agent (LangGraph)│  S4 dashboard
  (Dagster)    │ assets/checks/partitions/ │      │ read_as_of + analytics      │      │ tools = core read fns    │  (as_of slider)
               │ schedules/backfills/      │      │ as_of param on every route  │      │ each threads as_of       │
               │ reconcile(GC)             │      └─────────────────────────────┘      └──────────────────────────┘
               └───────────┬───────────────┘
                           ▼ writes vintages                          ▲ reads
   ArcticDB-on-MinIO (store of record) + per-symbol version index   ──┘     Neo4j (entity graph; references Arctic symbols)
   Dagster instance: dedicated Postgres
```

`as_of` is first-class on every read path from S1 storage up to S4's slider. Provenance
(`source`, `source_url`, `fetched_at`, `vintage_reconstructed`) rides on every frame/vintage.

---

## 4. The unifying invariant: bitemporal point-in-time correctness (+ honesty boundary)

Two time axes live on every row:

- **`valid_time`** — the period a row *describes* (canonical tz-aware UTC).
- **`as_of`** — the *knowledge/release* timestamp (when we learned the values).

**The honesty boundary (`vintage_reconstructed`):** EIA v2 and ERCOT have **no vintage parameter
and revise inline**, so true point-in-time history can only be captured **going forward** from first
live capture. Backfilling a revised source produces today's already-revised values stamped with past
dates — *fabricated history*. Every vintage therefore carries a `vintage_reconstructed` flag:

- **True vintage** (`reconstructed=False`): we observed the source at that knowledge time (live).
- **Reconstructed baseline** (`reconstructed=True`): a backfilled snapshot of today's revised values.

The flag is **load-bearing**: it is a column AND a version-index field, surfaced in `read_as_of`
output, the S3 agent tool contract, and the S4 slider. A sentinel test asserts reconstructed
vintages are excluded from point-in-time backtests.

---

## 5. S1 — Unified Data Platform (buildable detail)

### 5.1 Directory tree (under `src/energex/`)

```
src/energex/
  core/                            # framework-agnostic; CI test asserts ZERO `import dagster|fastapi|langgraph`
    config.py                      # MIGRATE: keep LLM_/NEWS_/LOG_; ADD ArcticDBConfig(ARCTIC_*/MINIO_*),
                                   #   Neo4jConfig(NEO4J_*), ConnectorConfig(EIA_API_KEY, ERCOT_*, NOAA_TOKEN).
                                   #   KEEP `settings.database` as a property ALIAS -> LegacyDuckDBConfig so
                                   #   test_api_contract/test_database_ergonomics stay green (db_path preserved).
    exceptions.py                  # MOVE; ADD QualityGateError, StorageError, SymbologyError, PartitionError, VintageImmutableError
    logging_config.py              # MOVE; optional structlog (bind run_id, partition_key, symbol, as_of)
    rate_limiter.py                # MOVE reuse-as-is (token bucket)
    symbology.py                   # NEW: resolve(id)->(library,symbol); revision_mode(id); contracts_for(commodity)
    storage.py                     # NEW: ArcticDB bitemporal layer + version-index commit protocol + _to_polars (CROWN JEWEL)
    quality.py                     # NEW gate: pandera schemas + validate()  (distinct path from analysis/quality.py)
    llm.py                         # MIGRATE llm_providers.py; provider-native structured outputs, temperature=0
    graph.py                       # NEW: Neo4j upsert_entities (phase 9, non-blocking)
    connectors/
      base.py                      # MIGRATE sources/base.py -> Connector Protocol + FetchResult
      registry.py                  # MIGRATE sources/__init__.py -> get_connector(name)
      eia.py                       # REBUILD: EIA v2 gas storage + petroleum status (revision-lookback window)
      ercot.py                     # REBUILD: ERCOT Public REST (OAuth2 ROPC + subscription key), floor 2023-12-11
      weather.py                   # REBUILD: NOAA nClimDiv monthly fixed-width HDD/CDD (dated archive files)
      yfinance.py                  # MIGRATE data_fetcher.py: YFinanceIntraday + YFinanceDated (dev/research only)
      duckdb_legacy.py             # TRANSITIONAL: read existing energy.db -> FetchResult for one baseline load
  orchestration/                   # the ONLY package importing dagster
    partitions.py  resources.py  assets.py  checks.py  schedules.py  sensors.py
    reconcile.py                   # NEW: out-of-band GC/reconciliation asset (orphan-version cleanup, missed-vintage)
    migrate_duckdb.py  definitions.py
  analysis/                        # REUSE-AS-IS (Polars); reads swap to read_as_of via _to_polars in S2
    volatility.py futures.py dated_futures.py market_sentiment.py
    quality.py                     # KEPT AS-IS (post-hoc dashboard AUDIT). Gate is core/quality.py — no rename, no shim.
  visualization/charts.py          # REUSE-AS-IS (S2/S4)
  database.py                      # legacy DuckDB READ path; demoted, deprecated for writes
  service/ agent/                  # S2/S3 placeholders
deploy/dagster/{dagster.yaml,workspace.yaml}   # Postgres instance storage + retention; webserver+daemon share it
```

Import shims re-export moved `core` modules from old paths during transition so the 122 tests keep importing.

### 5.2 Connector contract (`core/connectors/base.py`)

```python
@dataclass(frozen=True)
class FetchResult:
    frame: pd.DataFrame       # MUST contain instrument_id, valid_time (tz-aware UTC), value cols
    source: str
    fetched_at: datetime      # tz-aware UTC wall-clock = KNOWLEDGE time (basis for as_of on live capture)
    source_url: str
    complete_over_range: bool # True if frame is the full as-known series for its valid_time span (merge vs replace)

class Connector(Protocol):
    source: str
    def fetch(self, window_start: date, window_end: date) -> FetchResult: ...
```

All connectors return pandas. `yfinance.py` converts Polars→pandas at the boundary; lift
`_dated_tickers`/`MONTH_CODES` + `normalize_datetime_to_utc`; replace hand-rolled retry with
**tenacity** and actually wire the (currently dead) timeout/retries config into httpx. For **revised**
sources the fetch window MUST include the source's revision lookback (EIA ≥ 5 weeks; ERCOT per its
restatement window) so each fetch carries the inline revisions.

### 5.3 Storage contract (`core/storage.py`) — the crown jewel

**Three per-source revision modes**, chosen from symbology:

- `degenerate` — never-revised bars (continuous intraday OHLCV). No vintage index.
- `bitemporal_replace` — each release is a COMPLETE as-known series (NOAA whole-file). Full write.
- `bitemporal_merge` — each release revises a window inline (EIA/ERCOT). Read-modify-write merge.

**The commit protocol** (resolves mid-write-SIGKILL, immutability, latest-version, and
snapshot-scoping issues):

```python
VINTAGE_COLS = ("as_of", "version", "fetched_at", "vintage_reconstructed")  # in {symbol}__vintages sidecar

def commit_vintage(lib, symbol, frame, *, as_of, source, source_url, fetched_at,
                   mode, reconstructed=False, force=False) -> int:
    idx = _read_vintage_index(lib, symbol)            # latest version of sidecar; [] if none
    if not force and any(v.as_of == as_of for v in idx):
        return _version_for(idx, as_of)               # IDEMPOTENT NO-OP: never re-fetch/mutate a live vintage
    frame = _canonicalize(frame, as_of, source, source_url, fetched_at)  # tz-naive-UTC index, sorted+unique
    if mode == "bitemporal_merge":
        prior = _read_full_series_at(lib, symbol, idx) # full as-known series before this release
        frame = _merge_revisions(prior, frame)         # revisions overwrite by valid_time; NEVER delete omitted rows
    # else bitemporal_replace: frame is already the complete series
    v = lib.write(symbol, frame, metadata={...}, validate_index=True).version   # NEVER prune_previous_versions
    # COMMIT POINT — single atomic append to the sidecar index:
    _append_vintage_index(lib, symbol, as_of=as_of, version=v,
                          fetched_at=fetched_at, vintage_reconstructed=reconstructed)
    lib.snapshot(f"{symbol}@{as_of:%Y-%m-%dT%H%M%SZ}", versions={symbol: v})  # convenience only; not authoritative
    return v

def write_bars(lib, symbol, frame, *, fetched_at) -> int:
    # DEGENERATE: append-with-dedup on the UTC DatetimeIndex. NEVER update(date_range) (would delete sparse gaps).
    existing = _existing_index(lib, symbol)
    new = frame[~frame.index.isin(existing)]
    return lib.append(symbol, new).version if len(new) else _latest_version(lib, symbol)

def read_as_of(lib, symbol, *, as_of=None, date_range=None) -> pd.DataFrame:
    if revision_mode(symbol) == "degenerate":
        df = lib.read(symbol, date_range=_naive(date_range)).data
        if as_of is not None:                          # filter on KNOWLEDGE time, not valid_time (no bar-latency leak)
            df = df[df["fetched_at"] <= as_of]
        return df
    idx = _read_vintage_index(lib, symbol)             # re-read every correctness-critical call (no stale in-proc cache)
    if as_of is None:
        v = _latest_committed_version(idx)             # LATEST = latest COMMITTED vintage, never an orphan write version
    else:
        floor = max((e for e in idx if e.as_of <= as_of), default=None, key=lambda e: e.as_of)
        if floor is None:
            return _empty_like(symbol)                 # as_of precedes earliest vintage => EMPTY, never fallback to latest
        v = floor.version
    return lib.read(symbol, as_of=int(v), date_range=_naive(date_range)).data   # exact-match by INT version

def read_curve(commodity, as_of) -> pd.DataFrame:      # NEW first-class assembler
    syms = symbology.contracts_for(commodity)          # CL_CLF26, CL_CLG26, ...
    frames = [read_as_of(*symbology.resolve(s), as_of=as_of) for s in syms]
    return _reassemble_curve(frames)                   # rebuild Commodity/ContractMonth multi-contract frame

def _to_polars(versioned_item) -> pl.DataFrame:        # THE single canonical adapter (index/tz/dtype seam)
    df = versioned_item.data.reset_index()             # ArcticDB returns DatetimeIndex; pl.from_pandas drops index
    df["Datetime"]   = df["Datetime"].dt.tz_localize("UTC")     # Arctic strips tz; re-localize
    df["valid_time"] = df["valid_time"].dt.tz_localize("UTC")
    pf = pl.from_pandas(df)
    if "ContractMonth" in pf.columns:                  # pandas has no date dtype -> came back datetime64
        pf = pf.with_columns(pl.col("ContractMonth").cast(pl.Date))
    return pf
```

**Vintage addressing:** authoritative **per-symbol version index** (sidecar `{symbol}__vintages`),
read by ArcticDB **integer version** (verified exact-match). NOT datetime-`as_of` (resolves to version
*write* time → collapses backfills to "now") and NOT snapshot `versions=` scoping (unverified,
crash-unsafe). The index append is the **atomic commit point**; a crash between data-write and
index-append leaves an orphan data version cleaned by the out-of-band GC. Named snapshots are a
human-navigable convenience for the Dagster UI only; **correctness never depends on them**. A Phase-0
experiment may later promote snapshots to authoritative.

**MinIO URI** built INSIDE `ArcticDBResource` from EnvVar fields (no secrets in URI literals); exact
grammar confirmed by a Phase-0 connectivity smoke test. **Library taxonomy:** `fundamentals.eia`,
`prices.power` (ERCOT), `weather`, `prices.futures` (dated, merge), `prices.intraday` (continuous,
degenerate), `curves` (derived, S2). **Concurrency:** until ArcticDB snapshot/index concurrency on
MinIO is verified, Dagster serializes writes per library (tag-based, max 1 concurrent run/library) so
the sidecar-index append never races.

### 5.4 Quality gate (`core/quality.py`)

```python
import pandera.pandas as pa
from energex.core.exceptions import QualityGateError

def validate(frame, schema: pa.DataFrameSchema, *, as_of) -> pd.DataFrame:
    try:
        return schema.validate(frame, lazy=True)       # lazy=True collects ALL failures in failure_cases
    except pa.errors.SchemaErrors as e:
        raise QualityGateError(schema_name=schema.name, failures=e.failure_cases) from e
```

Per-series schemas (`EIA_GAS_STORAGE`, `EIA_PETROLEUM`, `ERCOT_DALMP`, `NOAA_HDDCDD`, `OHLCV`,
`DATED_CONTRACTS`) enforce: column presence/dtype; no nulls in `(instrument_id, valid_time)`; value
sanity bands (storage ≥ 0, LMP band, HDD/CDD 0–9999 with `-9999.` sentinel coerced to NULL **before**
checks); row-count floor (empty = failure). Two DataFrame-level wide checks: `(instrument_id,
valid_time)` uniqueness; **freshness** — `max(valid_time)` within a **release-calendar-aware** lag of
`as_of` (not a fixed timedelta, to avoid holiday false-fails). The post-hoc `analysis/quality.py`
(`DataQualityChecker`) is unchanged and feeds dashboards only; the **gate** lives at the distinct
`core/quality.py` path — no rename, no import shim.

### 5.5 Symbology + revision modes (`core/symbology.py`)

`resolve(id) -> (library, symbol)` and `revision_mode(id) -> 'degenerate'|'bitemporal_merge'|'bitemporal_replace'`:

| instrument_id | library | symbol | mode |
|---|---|---|---|
| `EIA.NG.STORAGE.LOWER48` | `fundamentals.eia` | `ng_storage_lower48` | merge |
| `EIA.PET.CRUDE.STOCKS` | `fundamentals.eia` | `pet_crude_stocks` | merge |
| `ERCOT.DALMP.HB_HOUSTON` | `prices.power` | `dalmp_hb_houston` | merge |
| `NOAA.HDD.<region>` | `weather` | `hdd_<region>` | replace |
| `CME.CL.FRONT` | `prices.intraday` | `CL_FRONT` | degenerate |
| `CME.CL.CLF26` | `prices.futures` | `CL_CLF26` | merge |

Static dict in S1. **Guardrail:** storage asserts a frame with multiple `as_of` values, or any symbol
in a bitemporal library, must NOT route through `write_bars`; a unit test asserts every symbology
entry's `revision_mode` matches its library class.

### 5.6 Dagster modeling (`orchestration/`) — verified against Dagster 1.13.9

- **Partitions:** EIA gas `WeeklyPartitionsDefinition(start_date='2020-01-02', day_offset=4)`; EIA
  petroleum weekly (Wed); ERCOT `DailyPartitionsDefinition(start_date='2023-12-11')`; NOAA
  `MonthlyPartitionsDefinition`.
- **`as_of` derivation:** `as_of` is the **knowledge timestamp**, never `partition_time_window.end`.
  LIVE scheduled tick → `as_of` = schedule run time (= release time); BACKFILL → `as_of = fetched_at`
  with `reconstructed=True`. The partition key indexes the `valid_time` period; the asset maps
  period→`valid_time` range explicitly per source.
- **LIVE vs BACKFILL split:** if the partition's release is happening now → true vintage. If the
  partition predates live-capture-start → write ONE **reconstructed** baseline vintage
  (`as_of=fetched_at, reconstructed=True`), not one fake snapshot per historical period. A
  reverse-order-backfill regression test asserts no later data leaks into an earlier `as_of`.
- **Asset body (thin):** `as_of, reconstructed = _knowledge_time(context)`;
  `result = Connector(http).fetch(window_start, window_end)`;
  `frame = quality.validate(result.frame, SCHEMA, as_of=as_of)`;
  `lib, sym = symbology.resolve(id)`; `mode = symbology.revision_mode(id)`;
  `commit_vintage(...)` (or `write_bars` if degenerate);
  `return dg.MaterializeResult(metadata={...})` — JSON-serializable values only.
- **Checks:** `@asset_check` calls the SAME `core.quality.validate` (single-sourced gate) PLUS a
  post-write read-back (vintage resolves, rows > floor, `as_of` column == committed `as_of`). UI
  visibility is best-effort; the real safety net is `reconcile.py`. Checks MUST be passed explicitly
  to `Definitions(asset_checks=[...])`.
- **Resources:** `ConfigurableResource` + `EnvVar()`. `ArcticDBResource.setup_for_execution` builds
  the MinIO URI from env and opens Arctic with a **scoped service-account key** (not MinIO root).
  `HttpResource` = httpx + tenacity. `ercot` resource owns OAuth2 ROPC token caching/refresh (1h, no
  refresh) + 30 req/min throttle + tenacity 429 backoff + a startup geo-block probe that fails loud.
  `Neo4jResource` uses `driver.execute_query`.
- **Schedules** (always set `execution_timezone`; cron defaults to UTC): EIA gas `'30 10 * * 4',
  execution_timezone='America/New_York'`; petroleum `'30 10 * * 3'`; ERCOT daily; NOAA monthly ~6th;
  intraday frequent during CME hours (replaces APScheduler 5-min). `QueuedRunCoordinator`, low
  `max_concurrent_runs`, per-library concurrency tags so backfills serialize.
- **`reconcile.py`:** a daemon-scheduled OUT-OF-BAND asset that (1) lists data versions vs sidecar-index
  entries per symbol and cleans ORPHAN versions (crash residue), (2) checks the release calendar vs
  committed vintages and launches catch-up backfills for missed releases (flagged reconstructed),
  (3) emits metadata on leaked versions / missed windows for operator alerting.
- Backfills are idempotent because `commit_vintage` no-ops when the `as_of` already exists.

### 5.7 Futures → ArcticDB migration (retire the APScheduler/DuckDB island)

1. **One-shot baseline** (`migrate_duckdb.py` + `duckdb_legacy` connector): mount `energex-data`
   READ-ONLY, open `energy.db` with `read_only=True` (avoid single-writer lock contention),
   Polars→pandas, write `prices.intraday` (degenerate) and `prices.futures` (one reconstructed
   baseline vintage); verify row counts vs DuckDB.
2. `intraday_prices` → `prices.intraday` via `write_bars` (append-with-dedup; re-runs idempotent).
   Schema gains `valid_time/as_of/source_url/fetched_at`.
3. `daily_contracts` → `prices.futures` per-contract symbols, `bitemporal_merge`.
   `DatedFuturesAnalyzer.curve_as_of` stays byte-for-byte; S2 feeds it `read_curve(commodity, as_of)`
   through `_to_polars` (ContractMonth re-cast to `pl.Date`).
4. yfinance survives only as a dev/research adapter; Databento (R14) slots into the identical
   `Connector` contract later. `/healthz` rewritten to ArcticDB **before** cutting DuckDB;
   `ENERGEX_INGEST_CRON`/DuckDB env removed in the same commit; APScheduler + `main.py` retired once
   baseline verified; `database.py` demoted to read-only.

### 5.8 Always-on infra (docker-compose + Dagster instance)

- **Dagster instance storage = dedicated Postgres** (NOT SQLite — file-locking fails under concurrent
  webserver+daemon).
- **Profiles:** `dev` = minio + dagster-postgres + webserver + daemon; `full` = adds neo4j + energex
  FastAPI (S2).
- All services: `restart: unless-stopped`, `init: true`,
  `depends_on:{condition: service_healthy}`, json-file log rotation, **named volumes** (never macOS
  bind-mounts).
- **Resource limits on every service** (OOM = a mid-write event): explicit `mem_limit`/`cpus`; Neo4j
  heap+pagecache capped via `NEO4J_server_memory_*`; published min-RAM + sizing table.
- **Postgres and MinIO on separate named volumes** (avoid correlated disk-full).
- **MinIO** (`quay.io/minio/minio`, :9000/:9001): healthcheck verified present in the pinned tag by a
  cold-start compose smoke test; idempotent `mc` bucket-create init (`arctic` bucket); a scoped
  service account/key for ArcticDB, root only for provisioning.
- **Backups:** nightly maintenance window **pauses Dagster schedules/sensors** to quiesce writes, then
  `mc mirror` + `pg_dump` + `neo4j-admin dump` in the SAME quiesced window (shared consistency point).
  An automated **restore drill** into a throwaway namespace runs `read_as_of` on a known vintage and
  asserts equality — **a green drill is an S1 exit gate.**
- Dagster data-retention (tick/run/event + compute-log) configured in `dagster.yaml`. Backend
  containers `TZ=UTC`; wall-clock only via `execution_timezone`.
- pyproject extras: `orchestration` (dagster, dagster-webserver, dagster-postgres), `storage`
  (arcticdb), `quality` (pandera), `graph` (neo4j); keep `service`; mypy overrides for
  arcticdb/dagster/pandera/neo4j; dev adds `respx`.

### 5.9 Existing tests/modules reuse — honest classification

- **REUSE-AS-IS** (storage-invariant math): `test_volatility(_methodology)`, `test_quality`,
  `test_futures`, `test_dated_futures` (ONLY after the `_to_polars` ContractMonth round-trip test is
  green), `test_charts`, `test_sentiment_hardening`, `test_news_*`, `test_rate_limiter`,
  `test_exceptions`, `test_llm_factory`, `test_sources`, `test_timezone` (DuckDB part).
- **MIGRATE** (rewritten for ArcticDB/Dagster): `test_database` → `test_storage_pointintime.py`;
  `test_database_ergonomics` → `test_storage_ergonomics.py`; `test_data_fetcher` →
  `test_connectors_*.py` (respx fixtures, offline); `test_service.py` (rewrite `_seed` to ArcticDB
  writes, DROP scheduler tests, repoint pipeline tests at Dagster asset bodies); `test_sentiment.py`
  (the join is a behavioral rewrite — bound on `fetched_at`; update look-ahead/tz/fan-out
  expectations); `test_main.py` (read-only `--check` if CLI kept, else delete). `test_config`/
  `test_api_contract` stay green via the `settings.database` alias.
- **ADD:** `test_core_has_no_framework_imports.py`; `test_pandera_schemas.py` (pass + deliberate-fail);
  `test_definitions_load.py`; `test_storage_roundtrip.py` (tz-aware-UTC + dtype incl. ContractMonth
  in==out); `test_pointintime_reverse_backfill.py` (backfill in reverse `as_of` order, assert no
  future leak; `as_of < earliest ⇒ empty`); `test_crash_safety.py` (kill between data-write and
  index-append, assert `read_as_of` returns the prior vintage, never an older one);
  `test_write_bars_sparse.py` (store t1,t3; re-ingest only t2; assert t1,t3 survive);
  `test_revision_merge_gap.py` (revision frame with a gap must not delete a prior row);
  `test_sentiment_pointintime` (no article with `fetched_at > X` appears at `read_as_of(X)`).
- **RETIRE** root `test_phase_1_3.py` / `test_phase_4.py` after migrating unique asserts.
- **CI gains:** `no-framework-imports` job, `definitions` (`dagster definitions validate`) job,
  cold-start compose smoke-test job.

### 5.10 Phase-by-phase S1 build order (run `uv run dagster dev` after each; gate in brackets)

0. **PRE-BUILD discovery + experiments** [EIA series IDs + `facets[series][]` spelling frozen from the
   metadata endpoint; ArcticDB-on-MinIO connectivity smoke test passes; empirical snapshot-scoping
   experiment decides snapshot vs version-index authority (default: version-index)].
1. **Scaffold** core + config (with `settings.database` alias) + extras; empty `Definitions`
   [Definitions loads; no-framework-imports test green; `test_config`/`test_api_contract` green].
2. **storage.py** (version-index commit protocol + `_to_polars`) + minio + dagster-postgres
   [round-trip tz+dtype; two-vintage point-in-time proof; reverse-order backfill no-leak;
   `as_of<earliest⇒empty`; crash-safety kill-between-write-and-index; `write_bars` sparse;
   revision-merge gap — ALL green and CI-gated].
3. **quality.py** + pandera schemas [pass + deliberately-failing frames blocked with `QualityGateError`].
4. **EIA gas connector** (revision-lookback window) + schema + respx fixture [connector test green offline].
5. **First asset** (EIA gas) + `asset_check` + `ArcticDBResource` (scoped key) + `reconcile.py`
   skeleton [materialize one LIVE partition; vintage resolves; orphan-version GC verified by injected orphan].
6. **Thu 10:30 ET schedule** + small backfill [backfill writes ONE reconstructed baseline
   (`reconstructed=True`), NOT fake weekly vintages; re-run is a no-op].
7. **EIA petroleum**, then **ERCOT** (OAuth2 + throttle + geo probe, floor 2023-12-11), then **NOAA**
   (monthly fixed-width, dated archive files for true historical vintages) [each materializes + checks pass].
8. **Futures migration** (RO baseline load; intraday `write_bars`; dated `bitemporal_merge`) [row
   counts match DuckDB; `read_curve` + `DatedFuturesAnalyzer` green via `_to_polars`]; cut DuckDB write
   path; rewrite `/healthz` first.
9. **(Last, non-blocking) Neo4j** entity upsert with `neo4j.time.DateTime` `valid_from`/`valid_to`
   [entities upserted; time-series path unaffected]. **Restore-drill automation green = S1 exit gate.**

---

## 6. Sequencing

**PRE-S1** (additive, low-risk, before building): extend `pyproject.toml` with
orchestration/storage/quality/graph extras + mypy overrides; extend `docker-compose.yml` with minio
(separate volume) + dagster-postgres (separate volume) + webserver + daemon + neo4j, with per-service
`mem_limit`/`cpus` and profiles dev/full; add the `settings.database` alias; extend CI with
no-framework-imports, definitions-load, and cold-start compose smoke-test jobs; delete the two ad-hoc
root `test_phase_*.py` scripts (after migrating unique asserts).

**S1 Phase 0** (gating experiments, before any storage code): freeze EIA series IDs/facet spelling
from the metadata endpoint; ArcticDB-on-MinIO connectivity smoke test (confirm exact URI grammar);
empirical ArcticDB snapshot-scoping experiment (decides snapshot vs version-index authority — default
version-index).

**S1** (foundation, built first): phases 1–9 above. **Exit criteria:** EIA gas+petroleum, ERCOT, NOAA
materialize on schedule with passing checks; the bitemporal CI gate suite (point-in-time proof,
reverse-order no-leak, crash-safety, tz+dtype round-trip, sparse-bars, revision-merge-gap) is green;
futures migrated off DuckDB; `reconcile.py` cleans orphans and catches missed releases; restore-drill
green; always-on stack runs 24/7 on the US Mac Studio host; core has zero framework imports.

**S2 — analytics + FastAPI** (can START as soon as S1 phase 5 produces a real vintage): rebuild
`service/app.py` (drop APScheduler; reads via `read_as_of` in a threadpool; bounded reads; `/healthz`
on ArcticDB rewritten BEFORE DuckDB cut); add `as_of` to every endpoint; reuse
volatility/futures/dated_futures/charts via `_to_polars`; `/curve` uses `read_curve`. Migrate
`market_sentiment` to point-in-time (3-stage; read-time join bounded on `fetched_at`; temperature=0;
provider-native structured outputs; fixed 3× fan-out) as a deliberate rewrite with new tests.

**S3 — LangGraph agent** (after S2 read API stable): tools = core read/analytics functions threading
`as_of` and surfacing `vintage_reconstructed`; point-in-time sentinel regression tests; decide
read-only vs orchestration-trigger authority (default read-only).

**S4 — frontend/dashboards** (after S2/S3): dashboard over S2 JSON + Plotly + S3 chat; `as_of`
time-travel slider flagging reconstructed vs true vintages; Dagster webserver operators-only.

R14 (licensed futures feeds) is a decision-gated XL track that runs alongside S2 without blocking it.

---

## 7. Key decisions & rationale

1. **Per-symbol version index, read by integer version** (not datetime-`as_of`, not snapshot scoping).
   Verified: datetime-`as_of` resolves to version *write* time (collapses backfills to "now");
   integer-version reads are exact-match; snapshot `versions=` scoping is unverified and crash-unsafe.
2. **The sidecar-index append is the commit point.** OrbStack/host SIGKILLs in-flight runs; a
   delete-then-recreate-snapshot path could permanently delete a published vintage and make
   `read_as_of` silently return an older wrong vintage. Append-only index + out-of-band GC removes the
   destructive window.
3. **`vintage_reconstructed` honesty flag.** EIA v2 + ERCOT revise inline with no vintage parameter;
   backfilled history is fabricated. The flag lets backtests/the agent refuse reconstructed data.
4. **`as_of` = knowledge time** (run time live / `fetched_at` backfill), never
   `partition_time_window.end` (a data-period boundary). Keeps the two axes separate.
5. **Three revision modes from symbology.** One write model can't serve never-revised intraday bars,
   inline-revision merges, and whole-file replaces. `lib.update(date_range)` would silently delete
   omitted rows.
6. **Single canonical `_to_polars` adapter.** ArcticDB is pandas-only, strips tz, is index-based;
   naive `pl.from_pandas` drops the index, loses tz, and turns ContractMonth into datetime64.
7. **Dagster instance on dedicated Postgres; per-service mem/cpu limits; separate volumes;
   QueuedRunCoordinator with per-library write serialization.** SQLite fails multi-process; unbounded
   containers OOM the VM (= mid-write event); per-library serialization sidesteps unverified ArcticDB
   concurrency on MinIO.
8. **Keep `settings.database` alias + `analysis/quality.py` unchanged.** Keeps existing tests green;
   no name-collision between the pre-write GATE (`core/quality.py`) and post-hoc AUDIT.
9. **ERCOT via Public REST API (floor 2023-12-11); NOAA via monthly nClimDiv files.** Verified: "Data
   Miner 2" is PJM-only; ERCOT is geo-blocked/rate-limited/token-no-refresh with no pre-2023-12-11
   API; NOAA has no live API but dated archive files support true historical vintages.
10. **Quiesced backups across all three stores + automated restore drill as an S1 exit gate.**
    mc-mirroring a live ArcticDB yields dangling refs; an untested backup of the store of record is the
    single highest-impact unproven step.

---

## 8. Risks & mitigations

1. **Honesty flag must be respected by every consumer** — else fabricated baselines look like observed
   history. *Mitigation:* flag is a column AND index field, surfaced everywhere; sentinel test excludes
   reconstructed vintages from backtests.
2. **The version-index sidecar is the single addressing source of truth** — a non-atomic append
   corrupts all point-in-time reads. *Mitigation:* append-only; re-read every correctness-critical
   call; crash-safety test; daily reconciliation cross-check.
3. **ArcticDB concurrency on MinIO unverified** — design serializes writes per library, capping
   backfill throughput. *Mitigation:* Phase-0 experiment; relax only after a passing N-parallel stress test.
4. **Host availability** — even a Mac Studio could be offline across a release window; Dagster does not
   auto-catch-up missed ticks, and a missed live EIA/ERCOT release is a permanently un-capturable TRUE
   vintage. *Mitigation:* reconciliation sensor with immediate catch-up (flagged reconstructed) +
   external heartbeat alert when the stack is down across a known release window.
5. **Read-modify-write merge reads the full prior series per release** — grows per-write cost for
   high-cardinality symbols. *Mitigation:* bound symbol size, monitor, per-symbol libraries if needed.
6. **Snapshot/version + Dagster event/log growth fills the shared disk** (disk-full = a crash event).
   *Mitigation:* separate volumes, Dagster retention, log rotation, disk alerting.
7. **The `_to_polars` tz/dtype seam is a silent-corruption class even centralized.** *Mitigation:*
   round-trip dtype+tz CI gate + explicit tz-aware `date_range` test that fails loud.
8. **~6 always-on containers incl. Neo4j (JVM) on one VM** — a 16GB host may be marginal under
   backfill. *Mitigation:* sizing table, minimal dev profile (no neo4j), tuned-small Postgres, capped
   Neo4j heap; re-evaluate whether Neo4j must be always-on.
9. **ERCOT US-geo-block** — non-US runs hard-fail. *Mitigation:* respx-fixture tests, startup geo-probe
   that fails loud, documented US-egress prerequisite (satisfied by the Mac Studio host).
10. **Transition window with both DuckDB and ArcticDB live.** *Mitigation:* rewrite `/healthz` to
    ArcticDB first; cut the DuckDB write path in one decisive commit after row-count verification.

---

## 9. Acceptance criteria / S1 exit gates

- `energex.core` contains no `import dagster|fastapi|langgraph` (CI-enforced).
- `uv run dagster dev` loads `Definitions` (assets, asset_checks, schedules) with no errors.
- Materializing an EIA partition writes a new ArcticDB version + named snapshot stamped with that
  partition's knowledge `as_of`.
- **Point-in-time proof:** two vintages where the later revises an earlier period →
  `read_as_of(earlier)` returns pre-revision values, `read_as_of(later)` returns revised values.
- **Reverse-order backfill:** no future leak; `as_of < earliest ⇒ empty`.
- **Crash-safety:** kill between data-write and index-append → `read_as_of` returns the prior vintage,
  never an older one; the orphan version is GC'd.
- A deliberately malformed frame fails the asset check and is **not** written.
- A partitioned backfill of K partitions is green and idempotent (re-run = no-op).
- No secret is hardcoded; all credentials from env.
- Full unit suite green (the honest reuse/migrate/add classification in §5.9).
- `full` compose profile comes up healthy with the daemon firing schedules; **restore drill green.**

---

## 10. Resolved open questions

| Question | Resolution |
|---|---|
| Futures source for v1 | yfinance dev/research adapter only; Databento/ICE deferred (paid R14). |
| Weather granularity | Monthly nClimDiv HDD/CDD; daily GHCN-Daily deferred. |
| Vintage retention | Keep all vintages forever (revisit on disk pressure). |
| Always-on host | User's always-on Mac Studio (`100.113.71.18`); US-egress confirmed by geo-probe. |
| Neo4j in S1 | Yes, non-blocking phase 9; symbology stays a static dict the graph references. |
| S3 agent authority | Default read-only; trigger authority revisited at S3. |

---

## 11. Verified external APIs (June 2026) — build reference

> Confirmed against live docs during design. Build agents should re-confirm anything marked *Phase-0*.

**ArcticDB 6.18.1.** `Arctic(uri)`; `library.write/append/update/read/snapshot`; `read(symbol,
as_of=...)` where `as_of ∈ {int version, str snapshot, datetime}`. **Gotchas:** datetime-`as_of` =
"version latest at that wall-time" (NOT a data knowledge date) → use **int version**; **timezone is
stripped** from stored timestamps (re-localize on read); **Polars not supported for write** (convert
to pandas); `prune_previous_versions=True` breaks historical `as_of` (never use); `append` has no
concurrent-write-to-one-symbol support; `validate_index=True` needed for `date_range` reads.

**Dagster 1.13.9.** `@asset(partitions_def=...)`, `@asset_check(asset=...)`, `Definitions(assets,
asset_checks, schedules, resources)`. `context.partition_time_window` is a `TimeWindow` with `.start`/
`.end` **properties** (not methods). **Postgres strongly recommended** over SQLite for
webserver+daemon; all processes share one `dagster.yaml` via `DAGSTER_HOME`. Cron without
`execution_timezone` defaults to UTC. `asset_checks` MUST be explicit in `Definitions`. Python ≥ 3.10.

**pandera.** Import `pandera.pandas as pa`; `DataFrameSchema(columns, checks=[...])`; `schema.validate(df,
lazy=True)` raises `pa.errors.SchemaErrors` with `.failure_cases`. Polars support exists but pandas is
first-class (used here).

**EIA v2.** `api_key` query param; requests take `frequency`, `data[0]=value`, `facets[...]`,
`start`/`end`, `offset`/`length`. *Phase-0:* freeze exact gas-storage + petroleum-status route slugs
and facet field names from the metadata endpoint at <https://www.eia.gov/opendata/>. Weekly releases
revise prior weeks inline (≥ 5-week lookback window).

**ERCOT Public REST API** (`api.ercot.com`). OAuth2 ROPC + `Ocp-Apim-Subscription-Key`; token ~1h, no
refresh; ~30 req/min; **US-geo-blocked**; history floor **2023-12-11**. Day-ahead LMP/SPP + load.
Tests use recorded respx fixtures; a startup geo-probe fails loud.

**NOAA nClimDiv.** Monthly HDD/CDD by region as fixed-width download files (no live API); dated archive
files provide true historical vintages. `-9999.` sentinel → NULL before quality checks.

**Neo4j (driver) + MinIO.** Idempotent `MERGE` via `driver.execute_query`; temporal edge props as
`neo4j.time.DateTime` (`valid_from`/`valid_to`). MinIO `quay.io/minio/minio` (:9000/:9001) as the
ArcticDB S3 backend; URI built from env inside `ArcticDBResource`; *Phase-0* connectivity smoke test
confirms exact URI grammar; scoped service-account key for ArcticDB.

---

## 12. Deployment host

Runs on the user's **always-on Mac Studio** (reachable at Tailscale `100.113.71.18`) — a non-laptop,
non-sleeping, US-resident host. This satisfies the always-on prerequisite for true forward vintage
capture and ERCOT's US-egress requirement (verified by the startup geo-probe). The full stack
(minio + dagster-postgres + dagster-webserver + dagster-daemon + neo4j + energex FastAPI) runs under
`docker-compose --profile full` with `restart: unless-stopped`.
