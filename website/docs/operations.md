---
id: operations
title: Operations
sidebar_label: Operations
---

# Operations

Day-to-day running of the always-on power-data platform: the schedules and their
cadence, monitoring materializations and asset checks in the Dagster UI, querying the
S2 read API, backfilling a partition range, and troubleshooting freshness and
credentials. For bringing the stack up, see [Deployment](./deployment.md); for the
ingestion model, see [Orchestration](./orchestration.md).

## Schedules

Every series is its own Dagster asset (fetch → `core.quality.validate` →
`storage.commit_vintage`/`write_bars`) wrapped in a partitioned job. Each schedule ships
`default_status=RUNNING`, so the daemon starts firing them the moment the stack comes up.
On every tick a schedule materializes the **most recent partition** resolved against the
tick's scheduled execution time. Crons set an explicit `execution_timezone` — the backend
runs `TZ=UTC`, so wall-clock release times live only in the schedule and the cadence stays
DST-correct.

| Schedule | Cron | TZ | Cadence | Asset(s) |
| --- | --- | --- | --- | --- |
| `eia930_schedule` | `20 * * * *` | America/New_York | hourly (~1–2h lag) | `eia930_region`, `eia930_generation_by_fuel` |
| `ercot_rt_spp_schedule` | `25 * * * *` | America/Chicago | hourly, current operating day | `ercot_rt_spp` |
| `ercot_load_schedule` | `35 * * * *` | America/Chicago | hourly, current operating day | `ercot_load` |
| `ercot_dam_spp_schedule` | `0 14 * * *` | America/Chicago | daily 14:00 CPT, **next** operating day | `ercot_dam_spp` |
| `fred_spot_prices_schedule` | `30 9 * * 1-5` | America/New_York | weekday mornings | `fred_spot_prices` |
| `eia_gas_storage_schedule` | `35 10 * * 4` | America/New_York | Thursday (post-release) | `eia_gas_storage` |
| `eia_petroleum_status_schedule` | `35 10 * * 3` | America/New_York | Wednesday (post-release) | `eia_petroleum_status` |
| `noaa_degree_days_schedule` | `0 12 6 * *` | America/New_York | 6th of each month | `noaa_degree_days` |

`intraday_futures_bars` is intentionally **not** scheduled — yfinance is dev-only, so a tick
would only fire failing runs. Materialize it by hand if you want it.

### ERCOT operating-day targeting

The EIA-930, FRED, EIA-weekly and NOAA schedules use the generic "latest available
partition" heuristic. ERCOT does not: its partitions are keyed by the **Central-time
operating day**, and the latest-ended partition lags a full day. Instead:

- **RT SPP and load** target the **current** operating day (`day_offset=0`) and
  re-materialize it hourly, so today's curve fills in as 15-minute SPPs and hourly load
  post intraday.
- **DAM SPP** targets **tomorrow's** operating day (`day_offset=+1`). The day-ahead market
  clears ~12:30–13:30 CPT, so the 14:00 tick fetches the next day's cleared curve.

If the target partition is not yet in range the schedule emits a `SkipReason` rather than a
failed run.

## Monitoring in the Dagster UI

The **Dagster UI** (`http://<host>:3000`) is the operator console.

- **Schedules** — confirm every schedule shows green/RUNNING and inspect recent ticks
  (including `SkipReason`s, which are normal for ERCOT before a partition is in range).
- **Runs** — materialization history, logs, and failures per asset.
- **Asset catalog** — each materialization carries metadata: `rows` written,
  `instrument_id`s, the committed `as_of`, ArcticDB `version`, `source_url`, and
  `vintage_reconstructed` (true for backfilled rows; see
  [Storage & Point-in-Time](./storage-point-in-time.md)).
- **Asset checks** — each series has a read-back check (below). A red check is the first
  signal that a committed vintage failed re-validation or a symbol went stale.

## Read-back asset checks

Selecting an asset in a job also pulls in its `@asset_check`. After the write, the check
**reads the committed bars back from ArcticDB and re-runs the same
`core.quality.validate(<schema>)`** the asset ran — proving the vintage resolves and still
passes the [quality gate](./orchestration.md). The freshness bound uses the `as_of` the
asset *committed* (the max read-back `as_of`), not wall-clock now, so a later check run
cannot false-flag data that was fresh when written.

| Check | Schema | Reads back from |
| --- | --- | --- |
| `eia930_region_pass_quality_gate` | `POWER_REGION` | `power.demand`, `power.demand_forecast`, `power.generation`, `power.interchange` |
| `eia930_generation_by_fuel_pass_quality_gate` | `POWER_GEN_BY_FUEL` | `power.generation_by_fuel` |
| `ercot_rt_spp_pass_quality_gate` | `ERCOT_SPP` | `power.lmp` |
| `ercot_dam_spp_pass_quality_gate` | `ERCOT_SPP` | `power.dalmp` |
| `ercot_load_pass_quality_gate` | `ERCOT_LOAD` | `power.load` |
| `eia_gas_storage_pass_quality_gate` | `EIA_GAS_STORAGE` | `fundamentals.eia` |
| `eia_petroleum_status_pass_quality_gate` | `EIA_PETROLEUM` | `fundamentals.eia` |
| `fred_spot_prices_pass_quality_gate` | `FRED_SPOT` | `prices.spot` |
| `noaa_degree_days_pass_quality_gate` | `NOAA_HDDCDD` | `weather` |
| `intraday_bars_pass_quality_gate` | `OHLCV` | `prices.intraday` |

### Per-symbol staleness

The power checks read back **every** symbol across their libraries (skipping the
`*__vintages` index sidecars). The schema's freshness check uses
`max(valid_time)` across all symbols, so one balancing authority that quietly stops
updating would not lower it. To catch that, the power checks compute `max(valid_time)`
per `instrument_id`, and any symbol lagging the freshest by more than **3 days** is
surfaced in the check's `stale_symbols` metadata (visible in the UI). The check still
passes — `stale_symbols` is a watch-list, not a failure — so scan it when an upstream BA
or settlement point looks suspect.

## Querying the S2 read API

The **S2 read API** (`energex.service.readapi`) is the read seam over the store, served on
host `:8000` by the compose `api` service. It is point-in-time first: every data endpoint
takes an optional `as_of` (ISO datetime) and defaults to the latest committed vintage.

```bash
# Liveness + the latest committed knowledge time across all symbols (open, no key needed)
curl http://<host>:8000/healthz

# Discover libraries and symbols
curl http://<host>:8000/libraries
curl 'http://<host>:8000/symbols?library=power.lmp'

# A bounded series read (ERCOT RT SPP at a hub, by valid_time window)
curl 'http://<host>:8000/series?library=power.lmp&symbol=hb_hubavg&start=2026-06-01&end=2026-06-02'

# Point-in-time: what did we KNOW about that window as of an earlier instant?
curl 'http://<host>:8000/series?library=power.lmp&symbol=hb_hubavg&as_of=2026-06-01T18:00:00Z'

# A benchmark forward curve as of a date
curl 'http://<host>:8000/curve?commodity=WTI&as_of=2026-06-01'
```

Operational notes:

- **Auth** — when `ENERGEX_READ_API_KEY` is set, every data endpoint requires a matching
  `X-API-Key` header (constant-time compared). `/healthz` stays open. Unset = open API with
  a startup warning in the logs.
- **`/series` row cap** — an unbounded full-history read is capped at
  `ENERGEX_SERIES_MAX_ROWS` (default 500000) and returns **413** if exceeded. Bound the
  read with `start`/`end` (a bounded read is exempt from the cap).
- **CORS** — cross-origin access is opt-in and origin-scoped via `ENERGEX_CORS_ORIGINS`
  (comma-separated allow-list); unset = no cross-origin access.

This API is the only contract the separate private frontend consumes — see
[Frontend Integration](./frontend-integration.md).

## Backfilling a partition range

To rebuild history (or recover a gap), launch a backfill over a partition range from the
Dagster UI (**Assets → select the asset → Materialize → backfill**) or from the CLI:

```bash
docker compose exec dagster-daemon \
  dagster job backfill ercot_rt_spp_job \
  --partition-range 2026-06-01:2026-06-07
```

Two honesty boundaries apply to backfills:

- Backfilled rows are flagged `vintage_reconstructed=True` — true point-in-time history
  accrues only going forward.
- ERCOT freshness is validated against the **partition end**, not wall-clock now, so
  backfilling an old operating day does **not** trip the freshness bound.

Because `commit_vintage` is content-idempotent, re-running a partition whose source data is
unchanged writes **no** new vintage — backfills are safe to re-run.

## Troubleshooting

**A schedule's runs fail immediately.** Almost always a missing or wrong credential. Each
connector reads its keys from `.env`: `EIA_API_KEY` (EIA-930 and the EIA-weekly
fundamentals), `ERCOT_USERNAME` / `ERCOT_PASSWORD` / `ERCOT_API_KEY_PRIMARY` (ERCOT B2C
auth + APIM subscription key), `FRED_API_KEY`, and `NOAA_TOKEN`. Check the failed run's logs
for the connector's auth/HTTP error before touching anything else. The MinIO/Arctic creds
(`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `ARCTIC_ACCESS_KEY`, `ARCTIC_SECRET_KEY`) have no
defaults — a missing one fails the whole stack, not a single asset.

**A run succeeds but its asset check is red.** The committed vintage failed re-validation.
The check metadata names the `schema` and the `failures` count (or `reason` when nothing
was read back). Inspect the offending series via `/series`.

**An asset check passes but lists `stale_symbols`.** One or more symbols are lagging the
freshest by more than 3 days. Confirm the upstream BA/settlement point is still publishing;
EIA-930 and ERCOT data update at least daily, so a persistent laggard is a real signal.

**ERCOT schedules only emit `SkipReason`.** Expected before the targeted operating-day
partition is in range (e.g. the DAM schedule before tomorrow's partition exists). It
becomes a problem only if a partition that *should* be in range is being skipped — check the
schedule's `execution_timezone` and the tick time.

**Health check.** `curl http://<host>:8000/healthz` returns `status`, the library list, and
`latest_as_of` (the newest committed knowledge time across all symbols, read cheaply from
the `*__vintages` sidecars). A stale or null `latest_as_of` means nothing has committed
recently — start at the Dagster schedules.

## Routine commands

```bash
docker compose --profile full ps                         # service + health status
docker compose --profile full logs -f dagster-daemon     # follow the scheduler's logs
docker compose --profile full logs -f api                # follow the S2 read API
docker compose --profile full restart dagster-webserver
docker compose --profile full down                       # stop (keeps volumes)
```
