---
id: intro
title: Introduction
sidebar_label: Introduction
slug: /
---

# Energex

**Energex is a self-hosted, always-on energy-market data platform with a bitemporal
(point-in-time-correct) store of record.**

It continuously ingests public energy data — EIA fundamentals, NOAA weather, FRED
benchmark spot prices, and (in development) intraday futures — runs every batch through
a quality gate, and commits it to a versioned ArcticDB store on MinIO. The store
remembers not only *what* a value was, but *when each value became known*, so you can
reconstruct exactly what the data looked like at any past moment.

## The problem it solves

Government and market data is **revised**. The U.S. Energy Information Administration
(EIA) restates weekly gas-storage and crude-stock figures for weeks after first
publication. NOAA reissues its monthly degree-day files. A naive database overwrites the
old number with the new one and silently rewrites history.

That quietly corrupts any backtest. If your model is trained or evaluated against data
that has since been revised, it is learning from numbers that *were not knowable* at the
decision point — so the backtest looks better than reality ever could.

## The core idea: two time axes

Energex records every observation against two independent clocks:

- **`valid_time`** — the period the row describes (for example, the week ending
  2026-05-30).
- **`as_of`** — the knowledge/release time: *when Energex learned this value.*

A single query answers "what did we know, and when did we know it":

```python
# What the series looked like as it was known on 2026-05-15.
df = read_as_of(symbol, as_of="2026-05-15")
```

`read_as_of` never leaks the future: it returns only data whose knowledge time is at or
before the requested `as_of`.

## The honesty boundary

Upstream sources like EIA and ERCOT revise **inline** and expose no vintage parameter.
That means true point-in-time history can only accrue **going forward**, from the day
Energex starts watching a series. Any history captured later by backfilling is, by
definition, a snapshot of *already-revised* data — not what was observed at the time.

Energex never pretends otherwise. Backfilled rows are flagged
`vintage_reconstructed=True`, so a backtest can exclude (or specially handle)
reconstructed baselines and never mistake them for genuine, observed-in-real-time
vintages. **That honesty flag is the platform's core invariant.**

## What's in the box

- A **pure domain core** (`energex.core`) — connectors, the bitemporal storage layer,
  a pandera quality gate, symbology, and configuration — with zero framework imports.
- A **Dagster orchestration layer** that schedules ingestion, runs quality checks, and
  keeps the store current with no manual intervention.
- An **always-on Docker stack** (MinIO, Dagster, Neo4j) you can run on a single host.
- Reserved layers for a read API (S2), an analytical agent (S3), and a commercial
  frontend (S4) — see the [Roadmap](./roadmap.md).

## Where to next

- [Architecture](./architecture.md) — the hexagonal layout and the bitemporal model.
- [Quickstart](./quickstart.md) — run the whole stack in a couple of commands.
- [Storage & Point-in-Time](./storage-point-in-time.md) — how vintages, revision modes,
  and the commit protocol actually work.
