---
id: orchestration
title: Orchestration
sidebar_label: Orchestration
---

# Orchestration

`energex.orchestration` is the **only** layer that imports Dagster. It turns the pure
core into an always-on pipeline: one asset per source, scheduled releases, post-write
quality checks, and the resources that connect to MinIO.

The whole thing loads from a single module:

```bash
uv run dagster dev -m energex.orchestration.definitions
```

`definitions.py` assembles assets, asset checks, schedules, sensors, and resources into a
single `Definitions` object that both `dagster dev` and the deployed webserver/daemon
load.

## Assets

Each asset follows the same shape: **fetch → quality gate → ArcticDB**, grouping the
frame by `instrument_id` and routing each through `symbology.resolve`.

| Asset | Group | Library | Source | Write path |
| --- | --- | --- | --- | --- |
| `intraday_futures_bars` | prices | `prices.intraday` | yfinance (manual) | `write_bars` (degenerate) |
| `fred_spot_prices` | prices | `prices.spot` | FRED (daily) | `write_bars` (degenerate) |
| `noaa_degree_days` | weather | `weather` | NOAA (monthly) | `commit_vintage` (`bitemporal_replace`) |
| `eia_gas_storage` | fundamentals | `fundamentals.eia` | EIA (weekly) | `commit_vintage` (`bitemporal_merge`) |
| `eia_petroleum_status` | fundamentals | `fundamentals.eia` | EIA (weekly) | `commit_vintage` (`bitemporal_merge`) |

For the bitemporal assets, `as_of` is the run's knowledge time, and the asset decides
`reconstructed` from the partition's age: if the partition's period closed longer ago
than a grace window (about 70 days for NOAA, about 10 days for EIA), the run is
backfilling already-revised data, so the vintage is committed with `reconstructed=True`.

## Partitions

| Partition | Definition | Drives |
| --- | --- | --- |
| `EIA_GAS_WEEKLY` | Weekly, `day_offset=4` (Thursday) | `eia_gas_storage` |
| `EIA_PETROLEUM_WEEKLY` | Weekly, `day_offset=3` (Wednesday) | `eia_petroleum_status` |
| `NOAA_MONTHLY` | Monthly | `noaa_degree_days` |
| `FRED_DAILY` | Daily | `fred_spot_prices` |

The partition key indexes the release period; the connector widens its pull to re-carry
publication lag and inline revisions (EIA looks back at least five weeks; FRED a short
daily window).

## Schedules

Four schedules are **running by default** (`DefaultScheduleStatus.RUNNING`). Each
materializes the most recent partition on every tick, with crons expressed in wall-clock
release time (the backend runs `TZ=UTC`, so `execution_timezone` is always set for
DST-correct cadence).

| Schedule | Cron (ET) | Fires |
| --- | --- | --- |
| `eia_gas_storage_schedule` | `35 10 * * 4` | Just after the Thursday 10:30 ET EIA gas release |
| `eia_petroleum_status_schedule` | `35 10 * * 3` | Just after the Wednesday 10:30 ET EIA petroleum release |
| `noaa_degree_days_schedule` | `0 12 6 * *` | 6th of the month, after the nClimDiv file lands |
| `fred_spot_prices_schedule` | `30 9 * * 1-5` | Weekday mornings, after FRED's publication lag |

`intraday_futures_bars` is intentionally **not scheduled** — yfinance is frequently
blocked, so a tick would only fire failing runs. Run it manually when you want intraday
data in dev.

## Asset checks (the quality gate, post-write)

Every source has an `@asset_check` that reads the committed series back from ArcticDB and
re-runs the **same** `core.quality.validate(...)` the asset ran on the way in
(re-localizing `valid_time` to UTC, which ArcticDB strips on store). This proves the
vintage resolves and still passes the gate after a real round-trip. The check is the
single-sourced gate run twice: once before the write, once after.

## Resources

`resources.py` defines the resources injected into assets and checks:

- **`ArcticDBResource`** opens an Arctic client against MinIO in `setup_for_execution`.
  Credentials come from Dagster `EnvVar` (`MINIO_ENDPOINT`, `ARCTIC_BUCKET`,
  `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`). ArcticDB's S3 backend requires the secret
  embedded in the connection URI, so the URI is **never logged** and any connection
  error is re-raised with a redacted message (endpoint/bucket only) so the credential
  cannot leak through a traceback. It hands out create-if-missing libraries.
- **`HttpResource`** is a thin `httpx` client factory for keyless/REST connectors.

## Backfills

Because every asset is partitioned, you can backfill historical data straight from the
Dagster UI: select an asset, choose a partition range, and launch a backfill. Remember
the honesty boundary — partitions older than the grace window commit with
`vintage_reconstructed=True`, so the backfilled history is correctly flagged as a
reconstructed baseline rather than a true forward vintage (see
[Storage & Point-in-Time](./storage-point-in-time.md)).

The Dagster UI runs on **http://localhost:3000** — it is the operator console (see
[Operations](./operations.md)).
