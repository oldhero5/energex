---
id: architecture
title: Architecture
sidebar_label: Architecture
---

# Architecture

Energex is a **bitemporal, point-in-time data platform for power markets**, built on a
**hexagonal (ports-and-adapters)** architecture. The domain core is pure and
framework-agnostic; each outer layer owns exactly one framework. This keeps the valuable,
hard-to-test logic — the connectors and the bitemporal store — free of framework
entanglement, and makes the boundaries explicit and enforceable.

## The layers

| Layer | Package | Responsibility | Status |
| --- | --- | --- | --- |
| **Core** (pure) | `energex.core` | Connectors, bitemporal storage, the pandera quality gate, symbology, schemas, config. No framework imports. | Built |
| **Orchestration** | `energex.orchestration` | The only Dagster importer: assets, checks, partitions, schedules, resources, reconcile, definitions. | Built |
| **Serving (S2)** | `energex.service` | A read-only FastAPI with `as_of` as a first-class parameter. | **Built — live on `:8000`** |
| **Agent (S3)** | `energex.agent` | A LangGraph analytical agent over the read API. | Reserved |

The **S4 frontend** is a separate private repository — the commercial product. It consumes
only the S2 read API; neither repo imports the other. That clean seam is the open-core
boundary (see the [Roadmap](./roadmap.md)).

## The core is framework-agnostic, and CI enforces it

`energex.core` must never import an application framework. This is not a guideline; it is a
test. `tests/test_core_has_no_framework_imports.py` walks every `.py` file under
`src/energex/core` and fails the build if any of them import `dagster`, `fastapi`, or
`langgraph`.

```python
# tests/test_core_has_no_framework_imports.py (essence)
FRAMEWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(dagster|fastapi|langgraph)\b")
# ... assert no file under src/energex/core matches.
```

The practical rule: business logic and storage live in the core; framework glue lives in
the layer that owns the framework. Orchestration and the read API import the core, never
the reverse.

## Data flow

```
power & supporting sources ──> Connector ──> quality gate ──> ArcticDB (MinIO)
EIA-930 (all BAs) · ERCOT       (core)        (pandera)        bitemporal store of record
RT/DA SPP + load · FRED ·                                            │
EIA fundamentals · NOAA                          ┌──────────────────┴───────────────────┐
                                                 ▼                                       ▼
                          Dagster (assets · schedules · checks · reconcile)   S2 read API (FastAPI)
                                                                                         │
                                                                                         ▼
                                                                          S4 frontend / S3 agent
```

1. A **connector** (`energex.core.connectors`) fetches a window from a source and returns a
   `FetchResult` — a dataframe with `instrument_id`, a tz-aware UTC `valid_time`, value
   columns, and provenance (`source`, `fetched_at`, `source_url`, `complete_over_range`).
   The live connectors are EIA-930 (region + by-fuel, all balancing authorities), ERCOT
   (real-time + day-ahead SPP and system load), and the supporting FRED / EIA-fundamentals /
   NOAA feeds. See [Data Sources & Connectors](./data-sources-connectors.md).
2. The **quality gate** (`energex.core.quality`, pandera schemas in `energex.core.schemas`)
   validates the frame *before* any write — dtypes, value bands, `(instrument_id,
   valid_time)` uniqueness, a row-count floor, and a release-calendar-aware freshness bound.
   The same `validate(...)` call runs in the asset and is re-run by the asset check, so the
   gate is a single source of truth.
3. The **storage layer** (`energex.core.storage`) commits to ArcticDB according to the
   instrument's revision mode, recording each vintage in a per-symbol `__vintages` index.
4. **Dagster** ties it together: one asset per series, scheduled releases, a read-back asset
   check per asset, and an orphan-reconcile asset.
5. The **S2 read API** (`energex.service.readapi`) serves the store point-in-time over HTTP —
   the only contract the frontend consumes. See
   [Frontend Integration](./frontend-integration.md).

## Symbology — the single router

`energex.core.symbology` maps an `instrument_id` to its `(library, symbol, revision_mode)`.
A static table covers the low-cardinality series; a rule-based `power.*` tail routes the
high-cardinality power namespace (e.g. `EIA930.D.<BA>` → `power.demand`, `ERCOT.SPP.<sp>` →
`power.lmp`) without enumerating the ~65–73 balancing authorities or every settlement point.
Mode is a property of the library, so bare power symbols never need to appear in a static
index.

## The bitemporal model

Every observation carries two time axes:

- **`valid_time`** — the period the row describes (e.g. the hour ending `2026-06-26T10:00Z`).
- **`as_of`** — the knowledge time: when Energex learned the value.

Reads are addressed by knowledge time. `read_as_of(lib, symbol, as_of=T)` resolves the
version that was current at `T` and returns it — never leaking anything learned after `T`.
With `as_of` omitted it returns the latest committed vintage.

### Revision modes

Each instrument is routed by symbology to exactly one revision mode, which determines how a
new release is committed:

| Mode | Meaning | Used by |
| --- | --- | --- |
| `degenerate` | Final, never-revised stream. Append-with-dedup; `as_of` = `fetched_at`. No vintage index. | EIA-930 (demand / forecast / generation / interchange / by-fuel), FRED spot, intraday bars |
| `bitemporal_merge` | Each release may revise a window *inline*. Read-modify-write merges the revision onto the prior as-known series, by exact `valid_time`. | ERCOT RT/DA SPP + load, EIA weekly fundamentals |
| `bitemporal_replace` | Each release is a *complete* as-known series. Full versioned write per `as_of`. | NOAA degree days |

`commit_vintage` is **content-idempotent**: a re-pull whose payload matches the latest
committed vintage writes no new vintage, so an unchanged hourly ERCOT re-materialization does
not grow the store.

### The honesty flag

True point-in-time history accrues only going forward, because EIA/ERCOT revise inline with
no vintage parameter. History captured later by backfilling is a snapshot of already-revised
data. Energex stamps those rows `vintage_reconstructed=True` so backtests never treat a
reconstructed baseline as something that was actually observed at the time. The orchestration
layer decides the flag from the partition's age: a partition whose period closed longer ago
than a grace window is a backfill of an already-revised release.

See [Storage & Point-in-Time](./storage-point-in-time.md) for the commit protocol, the
per-symbol version index, and crash safety.
