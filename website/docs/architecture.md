---
id: architecture
title: Architecture
sidebar_label: Architecture
---

# Architecture

Energex uses a **hexagonal (ports-and-adapters)** architecture. The domain core is pure
and framework-agnostic; the orchestration layer is the only place a framework (Dagster)
is allowed to appear. This keeps the valuable, hard-to-test logic — connectors and the
bitemporal store — free of framework entanglement, and makes the boundaries explicit
and enforceable.

## The four layers

| Layer | Package | Responsibility | Status |
| --- | --- | --- | --- |
| **Core** (pure) | `energex.core` | Connectors, storage, quality gate, symbology, schemas, config. No framework imports. | Built |
| **Orchestration** | `energex.orchestration` | The only Dagster importer: assets, checks, partitions, schedules, resources, reconcile, definitions. | Built |
| **Serving** | `energex.service` | FastAPI read API, `as_of` first-class. | Reserved (S2) |
| **Agent** | `energex.agent` | LangGraph analytical agent over the read API. | Reserved (S3) |

The **S4 frontend** is a separate private repository — the commercial product. It
consumes only the S2 read API; neither repo imports the other. That clean seam is the
open-core boundary (see the [Roadmap](./roadmap.md)).

## The core is framework-agnostic — and CI enforces it

`energex.core` must never import an application framework. This is not a guideline; it is
a test. `tests/test_core_has_no_framework_imports.py` walks every `.py` file under
`src/energex/core` and fails the build if any of them import `dagster`, `fastapi`, or
`langgraph`.

```python
# tests/test_core_has_no_framework_imports.py (essence)
FRAMEWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(dagster|fastapi|langgraph)\b")
# ... assert no file under src/energex/core matches.
```

The practical rule: business logic and storage live in the core; framework glue lives in
the layer that owns the framework. Orchestration imports the core, never the reverse.

## Data flow

```
sources ──> Connector ──> quality gate ──> ArcticDB (MinIO)
(EIA/NOAA/   (core)        (pandera)        bitemporal store of record
 FRED/yf)                                          │
                                                   ▼
                          Dagster (assets · schedules · checks · reconcile)
```

1. A **connector** (`energex.core.connectors`) fetches a window from a source and returns
   a `FetchResult` — a dataframe with `instrument_id`, a tz-aware UTC `valid_time`, value
   columns, and provenance (`source`, `fetched_at`, `source_url`).
2. The **quality gate** (`energex.core.quality`, pandera schemas) validates the frame
   *before* any write. The same `validate(...)` call runs in the asset and is re-run by
   the asset check — a single source of truth.
3. The **storage layer** (`energex.core.storage`) commits to ArcticDB according to the
   instrument's revision mode.
4. **Dagster** ties it together: one asset per source, scheduled releases, asset checks,
   and an orphan-reconcile asset.

## The bitemporal model

Every observation carries two time axes:

- **`valid_time`** — the period the row describes.
- **`as_of`** — the knowledge/release time, i.e. when Energex learned the value.

Reads are addressed by knowledge time. `read_as_of(symbol, as_of=T)` resolves the
version that was current at `T` and returns it — never leaking anything learned after
`T`. With `as_of` omitted, it returns the latest committed vintage.

### Revision modes

Each instrument is routed by `energex.core.symbology` to exactly one revision mode, which
determines how a new release is committed:

| Mode | Meaning | Used by |
| --- | --- | --- |
| `degenerate` | Never-revised stream. Append-with-dedup; `as_of` = `fetched_at`. No vintage index. | FRED spot, intraday bars |
| `bitemporal_replace` | Each release is a *complete* as-known series. Full versioned write per `as_of`. | NOAA degree days |
| `bitemporal_merge` | Each release revises a window *inline*. Read-modify-write merges the revision onto the prior as-known series, by exact `valid_time`. | EIA fundamentals |

### The honesty flag

True point-in-time history accrues only going forward, because EIA/ERCOT revise inline
with no vintage parameter. History captured later by backfilling is a snapshot of
already-revised data. Energex stamps those rows `vintage_reconstructed=True` so backtests
never treat a reconstructed baseline as something that was actually observed at the time.

The orchestration layer decides the flag from the partition's age: a NOAA or EIA
partition whose period closed longer ago than a grace window is a backfill of today's
already-revised file, so it is committed with `reconstructed=True`.

See [Storage & Point-in-Time](./storage-point-in-time.md) for the commit protocol, the
per-symbol version index, and crash safety.
