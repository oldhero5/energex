---
id: intro
title: Introduction
sidebar_label: Introduction
slug: /
---

# Energex

**Energex is a self-hosted, always-on power-markets data platform with a bitemporal
(point-in-time-correct) store of record.**

It continuously ingests public power-grid data, runs every batch through a quality gate,
and commits it to a versioned ArcticDB store on MinIO. The store remembers not only
*what* a value was, but *when each value became known*, so you can reconstruct exactly
what the data looked like at any past moment. Oil, gas, and weather are kept as
supporting context — power is the focus.

## What it ingests

Power is primary, and every source below is live:

- **EIA-930 Hourly Electric Grid Monitor** — the only required credential is
  `EIA_API_KEY`. Covers all ~65–73 US balancing authorities: hourly demand,
  day-ahead demand forecast, net generation, and interchange
  (`power.demand` / `power.demand_forecast` / `power.generation` / `power.interchange`),
  plus net generation **by fuel type** (`power.generation_by_fuel`). Connectors
  `Eia930RegionConnector` and `Eia930FuelConnector`; instrument ids
  `EIA930.{D,DF,NG,TI,GEN_FUEL}.<BA>` (symbol is the BA lowercased, e.g. `erco`, `ciso`).
- **ERCOT public API** — Azure AD B2C auth with an APIM subscription key
  (`ERCOT_USERNAME` / `ERCOT_PASSWORD` / `ERCOT_API_KEY_PRIMARY`). Real-time 15-minute
  settlement-point prices (`power.lmp`, `ERCOT.SPP.<sp>`), day-ahead hourly SPP
  (`power.dalmp`, `ERCOT.DASPP.<sp>`) for the 13 trading hubs and load zones, and
  ERCOT-wide actual system load (`power.load`, `ERCOT.LOAD.ERCOT`). Central Prevailing
  Time is converted to UTC, DST-correct.

Supporting context (deprioritized but live): EIA v2 weekly Lower-48 gas storage and US
crude stocks ex-SPR (`fundamentals.eia`), FRED daily WTI/Brent/Henry Hub spot
(`prices.spot`), and NOAA nClimDiv monthly HDD/CDD by region (`weather`). A
dev-only yfinance intraday connector exists for CL/BZ/NG but is **not** scheduled.

See [Data Sources & Connectors](./data-sources-connectors.md) for the full matrix.

## The problem it solves

Government and market data is **revised**. The EIA restates weekly gas-storage and
crude-stock figures for weeks after first publication. ERCOT and EIA-930 correct grid
values inline. NOAA reissues its monthly degree-day files. A naive database overwrites
the old number with the new one and silently rewrites history.

That quietly corrupts any backtest. If your model is trained or evaluated against data
that has since been revised, it is learning from numbers that *were not knowable* at the
decision point — so the backtest looks better than reality ever could.

## The core idea: two time axes

Energex records every observation against two independent clocks:

- **`valid_time`** — the period the row describes (for example, the hour beginning
  2026-05-30 14:00 UTC).
- **`as_of`** — the knowledge/release time: *when Energex learned this value.*

A single query answers "what did we know, and when did we know it":

```python
from energex.core.storage import read_as_of

# What the series looked like as it was known on 2026-05-15.
df = read_as_of(lib, symbol, as_of="2026-05-15")
```

`read_as_of` never leaks the future: it resolves against the *committed* vintage index
and returns only data whose knowledge time is at or before the requested `as_of`. Omit
`as_of` and you get the latest committed vintage. See
[Storage & Point-in-Time](./storage-point-in-time.md) for the revision modes
(`degenerate`, `bitemporal_merge`, `bitemporal_replace`) and the commit protocol.

## The honesty boundary

Upstream sources like EIA-930 and ERCOT revise **inline** and expose no vintage
parameter. That means true point-in-time history can only accrue **going forward**, from
the day Energex starts watching a series. Any history captured later by backfilling is,
by definition, a snapshot of *already-revised* data — not what was observed at the time.

Energex never pretends otherwise. Backfilled rows are flagged
`vintage_reconstructed=True`, so a backtest can exclude (or specially handle)
reconstructed baselines and never mistake them for genuine, observed-in-real-time
vintages. **That honesty flag is the platform's core invariant.**

## What's in the box

- A **pure domain core** (`energex.core`) — connectors, the bitemporal storage layer,
  a pandera quality gate, symbology, and configuration — with zero framework imports.
- A **Dagster orchestration layer** (one asset per series) that schedules ingestion,
  re-runs the quality gate as a read-back check, and keeps the store current with no
  manual intervention. See [Orchestration](./orchestration.md).
- A **live S2 read API** (`energex.service.readapi`, FastAPI) with `as_of` as a
  first-class parameter on every data endpoint: `/healthz`, `/libraries`, `/symbols`,
  `/series`, and `/curve`. Optional API-key auth (`ENERGEX_READ_API_KEY`) and
  origin-scoped CORS. This API is the only contract the separate private frontend
  consumes — see [Frontend Integration](./frontend-integration.md).
- An **always-on Docker stack** (MinIO, Dagster + Postgres, the read API, optional
  Neo4j) you can run on a single host with `docker compose --profile full up -d`.

## Where to next

- [Quickstart](./quickstart.md) — run the whole stack in a couple of commands.
- [Architecture](./architecture.md) — the hexagonal layout and the bitemporal model.
- [Storage & Point-in-Time](./storage-point-in-time.md) — how vintages, revision modes,
  and the commit protocol actually work.
- [Deployment](./deployment.md) and [Operations](./operations.md) — running and keeping
  the platform healthy.
- [Roadmap](./roadmap.md) — what's live and what's reserved (S3 agent, S4 frontend).
