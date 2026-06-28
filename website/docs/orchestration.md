---
id: orchestration
title: Orchestration
sidebar_label: Orchestration
---

# Orchestration

`energex.orchestration` is the **only** layer that imports Dagster. It turns the pure
[core](./architecture.md) into an always-on pipeline: one asset per series, a read-back
quality check on every asset, schedules that all ship **running**, and the resources that
connect to MinIO. The power feeds (EIA-930, ERCOT) are the focus; oil, gas, and weather
are supporting context.

The whole thing loads from a single module:

```bash
uv run dagster dev -m energex.orchestration.definitions
```

`definitions.py` assembles assets, asset checks, schedules, sensors, and resources into a
single `Definitions` object that both `dagster dev` and the deployed webserver/daemon
load.

## Assets

Each asset follows the same shape: **fetch → quality gate → ArcticDB**, grouping the
fetched frame by `instrument_id` and routing each group through `symbology.resolve`. The
write path is either `storage.write_bars` (degenerate, append-with-dedup) or
`storage.commit_vintage` (bitemporal merge/replace) — see
[Storage & Point-in-Time](./storage-point-in-time.md).

| Asset | Group | Library | Source (cadence) | Write path |
| --- | --- | --- | --- | --- |
| `eia930_region` | `power` | `power.{demand,demand_forecast,generation,interchange}` | EIA-930 (hourly) | `write_bars` (degenerate) |
| `eia930_generation_by_fuel` | `power` | `power.generation_by_fuel` | EIA-930 (hourly) | `write_bars` (degenerate) |
| `ercot_rt_spp` | `power` | `power.lmp` | ERCOT RT 15-min SPP (intraday) | `commit_vintage` (`bitemporal_merge`) |
| `ercot_dam_spp` | `power` | `power.dalmp` | ERCOT day-ahead SPP (daily) | `commit_vintage` (`bitemporal_merge`) |
| `ercot_load` | `power` | `power.load` | ERCOT actual system load (hourly) | `commit_vintage` (`bitemporal_merge`) |
| `fred_spot_prices` | `prices` | `prices.spot` | FRED (daily) | `write_bars` (degenerate) |
| `eia_gas_storage` | `fundamentals_legacy` | `fundamentals.eia` | EIA v2 (weekly) | `commit_vintage` (`bitemporal_merge`) |
| `eia_petroleum_status` | `fundamentals_legacy` | `fundamentals.eia` | EIA v2 (weekly) | `commit_vintage` (`bitemporal_merge`) |
| `noaa_degree_days` | `weather` | `weather` | NOAA nClimDiv (monthly) | `commit_vintage` (`bitemporal_replace`) |
| `intraday_futures_bars` | `prices_legacy` | `prices.intraday` | yfinance (manual) | `write_bars` (degenerate) |

The EIA-930 region asset fans a single fetch out across the four degenerate libraries
(`power.demand`, `power.demand_forecast`, `power.generation`, `power.interchange`) by
routing each `instrument_id` with `symbology.resolve`; one fetch covers **all ~65–73
balancing authorities**.

### Knowledge time and the honesty boundary

For a live capture, `as_of = fetched_at` — the knowledge time is simply when the run
pulled the data. For the bitemporal fundamentals/weather assets, the asset additionally
decides `reconstructed` from the partition's age: if the partition's period closed longer
ago than a grace window, the run is backfilling **already-revised** data, so the vintage
is committed with `vintage_reconstructed=True`.

```python
# assets.py — NOAA whole-file replace; ~70-day grace
_NOAA_LIVE_GRACE = timedelta(days=70)
# assets.py — EIA inline-revision; ~10-day grace
_EIA_LIVE_GRACE = timedelta(days=10)
```

ERCOT commits always set `reconstructed=False` — the schedules target live operating days
(below), and the partition-relative freshness check (also below) is what keeps a legitimate
same-day backfill from being mistaken for stale data. See
[Storage & Point-in-Time](./storage-point-in-time.md#revision-modes) for why a backfill
can never claim to be a true forward vintage.

## Partitions

`partitions.py` keys each series to its natural release period.

| Partition | Definition | Drives |
| --- | --- | --- |
| `EIA930_DAILY` | Daily, `start_date="2023-06-01"` (UTC) | `eia930_region`, `eia930_generation_by_fuel` |
| `ERCOT_DAILY` | Daily, `timezone="America/Chicago"`, `end_offset=2` | `ercot_rt_spp`, `ercot_dam_spp`, `ercot_load` |
| `EIA_GAS_WEEKLY` | Weekly, `day_offset=4` (Thursday) | `eia_gas_storage` |
| `EIA_PETROLEUM_WEEKLY` | Weekly, `day_offset=3` (Wednesday) | `eia_petroleum_status` |
| `NOAA_MONTHLY` | Monthly | `noaa_degree_days` |
| `FRED_DAILY` | Daily | `fred_spot_prices` |

The partition key indexes the release period; the connector widens its pull to re-carry
publication lag and inline revisions (EIA weekly looks back ≥5 weeks; EIA-930 and FRED a
short daily window).

### ERCOT operating-day mapping

`ERCOT_DAILY` is keyed by the **ERCOT operating day in Central Prevailing Time**, not UTC,
so a partition key maps 1:1 to an ERCOT delivery day. `end_offset=2` keeps **today and
tomorrow** as valid keys at once, because the three ERCOT feeds describe different
operating days:

```python
# partitions.py
ERCOT_DAILY = dg.DailyPartitionsDefinition(
    start_date="2026-06-01", timezone="America/Chicago", end_offset=2
)
```

- **RT SPP and system load** describe the **current** operating day, filling in hourly as
  the day progresses → their schedules target `day_offset=0`.
- **Day-ahead SPP** clears around 12:30–13:30 CPT for the **next** operating day → its
  schedule targets `day_offset=1`, fetching tomorrow's curve each afternoon.

The schedule helper `_ercot_day_request` computes the target key directly from the tick
date plus the offset, rather than "latest ended partition" (which lags a full operating
day and would be wrong for all three feeds).

## Schedules

Every schedule ships **running** (`DefaultScheduleStatus.RUNNING`) and sets
`execution_timezone` explicitly — the backend runs `TZ=UTC`, so wall-clock release times
live only here and the cadence stays DST-correct. The non-ERCOT schedules materialize the
**most recent partition** on each tick (`_latest_partition_request`); the ERCOT schedules
use the operating-day offset described above.

| Schedule | Cron | TZ | Fires |
| --- | --- | --- | --- |
| `eia930_schedule` | `20 * * * *` | America/New_York | Hourly, re-materializes today's EIA-930 partition (~1–2h source lag) |
| `ercot_rt_spp_schedule` | `25 * * * *` | America/Chicago | Hourly, re-materializes the current operating day (RT lands every 15 min) |
| `ercot_load_schedule` | `35 * * * *` | America/Chicago | Hourly, re-materializes the current operating day |
| `ercot_dam_spp_schedule` | `0 14 * * *` | America/Chicago | 14:00 CPT, fetches the next operating day's cleared curve |
| `eia_gas_storage_schedule` | `35 10 * * 4` | America/New_York | Just after the Thursday 10:30 ET EIA gas release |
| `eia_petroleum_status_schedule` | `35 10 * * 3` | America/New_York | Just after the Wednesday 10:30 ET EIA crude-stocks release |
| `noaa_degree_days_schedule` | `0 12 6 * *` | America/New_York | 6th of the month, after the nClimDiv file lands |
| `fred_spot_prices_schedule` | `30 9 * * 1-5` | America/New_York | Weekday mornings, after FRED's publication lag |

`intraday_futures_bars` is intentionally **not** scheduled — yfinance is frequently
blocked, so a tick would only fire failing runs. Run it manually when you want intraday
data in dev.

### Partition-relative freshness (so backfills pass)

The pandera freshness check (`core.schemas._freshness_check`) bounds `max(valid_time)`
against an `as_of` supplied per `validate` call — not wall-clock now. The ERCOT assets
exploit this: they validate against the **partition's end**, so backfilling an old
operating day does not falsely trip the 2-business-day bound.

```python
# assets.py — ercot_rt_spp
result = ErcotRtSppConnector().fetch(day, day)
return _commit_ercot(context, arctic, result, schemas.ERCOT_SPP, validation_as_of=window.end)
```

The bitemporal `as_of`/`fetched_at` that get **committed** stay the real knowledge time
(`result.fetched_at`); only the *freshness validation clock* is moved to the partition end.

## Asset checks (the quality gate, post-write)

Every asset has a paired `@asset_check` that reads the committed series **back** from
ArcticDB and re-runs the **same** `core.quality.validate(...)` the asset ran on the way in
(re-localizing `valid_time` to UTC, which ArcticDB strips on store). This proves the
vintage resolves and still passes the gate after a real round-trip — the single-sourced
gate, run twice: once before the write, once after.

Two details keep the read-back honest:

- **Committed `as_of`, not now.** The freshness re-check uses `_committed_as_of` — the max
  `as_of` provenance column in the read-back frame — so a check that runs hours later can't
  false-flag staleness for data that was fresh when written.
- **Per-symbol staleness surfacing.** The power read-backs (`_power_gate_readback`) span
  every symbol in a library. Because the schema freshness check keys on
  `max(valid_time)` across *all* symbols, a single BA that stopped updating wouldn't lower
  it — so any symbol lagging the freshest by more than `_STALE_SYMBOL_LAG`
  (`pd.Timedelta(days=3)`) is reported in the check's `stale_symbols` metadata.

UI visibility from checks is best-effort; the durable safety net is the reconcile sweep
(see [Operations](./operations.md)).

## Resources

`resources.py` defines the resources injected into assets and checks:

- **`ArcticDBResource`** opens an Arctic client against MinIO in `setup_for_execution`.
  Credentials come from Dagster `EnvVar` (`MINIO_ENDPOINT`, `ARCTIC_BUCKET`,
  `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`). ArcticDB's S3 backend requires the secret
  **embedded in the connection URI**, so the URI is **never logged** and any connection
  error is re-raised with a redacted message (endpoint/bucket only), so the credential
  cannot leak through a traceback. It hands out create-if-missing libraries.
- **`HttpResource`** is a thin `httpx` + `tenacity` client factory for keyless/REST
  connectors.

## Backfills

Because every production asset is partitioned, you can backfill historical data straight
from the Dagster UI: select an asset, choose a partition range, and launch a backfill.
Remember the honesty boundary — partitions older than the grace window commit with
`vintage_reconstructed=True`, so the backfilled history is correctly flagged as a
reconstructed baseline rather than a true forward vintage (see
[Storage & Point-in-Time](./storage-point-in-time.md)). The partition-relative freshness
clock means a same-day ERCOT backfill still passes the gate cleanly.

The Dagster UI runs on **http://localhost:3000** — it is the operator console (see
[Operations](./operations.md) and [Deployment](./deployment.md)).

## Adding a new asset + check + schedule

The layer is deliberately repetitive — every series follows the same three-part pattern.
To add one:

1. **Connector** — implement it in `energex.core.connectors` returning a `FetchResult`
   (frame carries `instrument_id`, tz-aware-UTC `valid_time`, value columns), and add its
   `instrument_id` routing rule in `core.symbology` (see
   [Data Sources & Connectors](./data-sources-connectors.md)). Add its pandera schema in
   `core.schemas`.
2. **Asset** in `assets.py` — fetch → `quality.validate(frame, SCHEMA, as_of=...)` → group
   by `instrument_id`, `symbology.resolve`, then `storage.write_bars` (degenerate) or
   `storage.commit_vintage` (bitemporal). Append it to `ASSETS`.
3. **Asset check** in `checks.py` — read the committed series back, re-run the **same**
   `quality.validate(...)`, return an `AssetCheckResult`. Append it to `CHECKS`.
4. **Partition** in `partitions.py` (if the series has a natural release period) and a
   **schedule** in `schedules.py` with `default_status=dg.DefaultScheduleStatus.RUNNING`
   and an explicit `execution_timezone`. Append it to `SCHEDULES`.

Everything is auto-wired by `definitions.py` from the `ASSETS` / `CHECKS` / `SCHEDULES`
lists — there is no central registry to edit beyond appending. Validate the result with
the Dagster CLI (the same gate CI runs — see [Testing](./testing.md)):

```bash
uv run dagster definitions validate -m energex.orchestration.definitions
```
