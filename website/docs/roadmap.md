---
id: roadmap
title: Roadmap
sidebar_label: Roadmap
---

# Roadmap

Energex is built in stages. **S1** (the data platform: core, storage, orchestration) and
**S2** (the read API) are **done and live** — they are what most of this documentation
describes. **S3** (an analytical agent) and **S4** (the commercial frontend) are reserved
in the package layout and summarized below.

| Stage | What | Status |
| --- | --- | --- |
| **S1** | Data platform: connectors, bitemporal store, quality gate, Dagster orchestration | **Done** |
| **S2** | FastAPI read API with `as_of` first-class on every data endpoint | **Done — live** |
| **S3** | LangGraph analytical agent over the read API | Reserved |
| **S4** | Immersive cross-device frontend (separate private repo) | Reserved |

## Focus: power markets

Energex is centered on **power markets**. The **EIA-930 Hourly Electric Grid Monitor**
ingests hourly today for all ~65–73 US balancing authorities: demand (`power.demand`),
day-ahead forecast (`power.demand_forecast`), net generation (`power.generation`),
interchange (`power.interchange`), and net generation by fuel type
(`power.generation_by_fuel`). **ERCOT** nodal data ingests live from the ERCOT public
API: real-time 15-minute and day-ahead hourly settlement-point prices for the trading
hubs and load zones (`power.lmp` / `power.dalmp`), plus ERCOT-wide actual system load
(`power.load`). Oil & gas and weather (FRED spot, EIA fundamentals, NOAA degree days)
remain ingested as supporting context but are no longer the focus.

**Next on the power track:** additional ISOs — **CAISO, PJM, MISO** — each following the
same connector contract and `power.*` symbology routing already used for EIA-930 and
ERCOT. See [Data sources & connectors](./data-sources-connectors.md) for the live
inventory.

## S1 — Data platform (done)

The pure domain core (`energex.core`) plus the Dagster orchestration layer. Connectors
fetch, the pandera quality gate validates every batch, and the bitemporal ArcticDB store
on MinIO records both *what* a value was and *when* it became known. One Dagster asset per
series, each with a read-back check and a `RUNNING` schedule. This is the foundation every
later stage builds on — see [Architecture](./architecture.md),
[Storage & point-in-time](./storage-point-in-time.md), and
[Orchestration](./orchestration.md).

## S2 — Read API (done — live)

A thin, read-only FastAPI seam over the bitemporal store (`energex.service.readapi`),
**served on host `:8000` by the compose `api` service**. It is the single read seam — the
place auth and rate-limiting live — and the **only contract the separate private frontend
consumes**. It is **point-in-time first**: every data endpoint takes an optional `as_of`
(ISO datetime) and defaults to the latest committed vintage.

| Endpoint | Returns |
| --- | --- |
| `GET /healthz` | Liveness, library list, and latest committed `as_of` (open, no key) |
| `GET /libraries` | The ArcticDB libraries present in the store |
| `GET /symbols?library=` | Symbols in a library (vintage sidecars excluded) |
| `GET /series?library=&symbol=&as_of=&start=&end=` | A series as known at `as_of`, optionally windowed |
| `GET /curve?commodity=&as_of=` | Dated-curve assembly as known at `as_of` |

Each `/series` row carries its provenance, including the `vintage_reconstructed` flag, so
consumers always know whether they are looking at a true forward vintage or a
reconstructed baseline.

Operational guardrails (all from `energex.service.readapi`):

- **Optional API-key auth** — set `ENERGEX_READ_API_KEY` and every data endpoint requires
  a matching `X-API-Key` header (constant-time compared); `/healthz` stays open. Unset
  leaves the API open with a startup warning.
- **Unbounded-read cap** — `/series` without `start`/`end` returns `413` past
  `ENERGEX_SERIES_MAX_ROWS` (default `500000`); bound the read with `start`/`end`.
- **Opt-in CORS** — `ENERGEX_CORS_ORIGINS` is a comma-separated origin allow-list (e.g.
  the frontend origin); unset means no cross-origin access.

```bash
# default vintage
curl 'http://localhost:8000/series?library=power.lmp&symbol=ERCOT.SPP.HB_HOUSTON'

# point-in-time: as the data was known on 2026-06-01, windowed
curl 'http://localhost:8000/series?library=power.demand&symbol=erco&as_of=2026-06-01T00:00:00Z&start=2026-05-01&end=2026-06-01'
```

Run it standalone with `uvicorn energex.service.readapi:app --workers 1`. See
[Deployment](./deployment.md) and [Frontend integration](./frontend-integration.md).

## S3 — Agent (reserved)

A LangGraph analytical agent in `energex.agent`, read-only, that threads `as_of` through
its queries so every answer is point-in-time correct. It calls the **live S2 API** rather
than touching storage directly — no new read path, no future leakage.

## S4 — Frontend (the commercial product, reserved)

The immersive, cross-device application — and the commercial offering — lives in a
**separate, private repository**. It is the paid product; this platform stays
source-available and free for noncommercial use. The two repos are joined only by the S2
read API: neither imports the other, and the app never touches ArcticDB/MinIO directly.

The design north star is an immersive, cinematic experience (WebGL/Three.js, scroll-driven
onboarding) wrapped around an instrument-grade daily "cockpit." The headline interaction is
an **`as_of` time-travel slider** that scrubs through knowledge time and visibly recolors
any series that is a **reconstructed** baseline versus a **true** forward vintage — making
the platform's honesty boundary a tangible product feature.

The full brief — including the open-core boundary diagram, the responsive-PWA strategy,
the design system, and the milestone plan — lives in the repository at
`docs/2026-06-18-s4-frontend-experience-design.md`:

- [S4 Frontend Experience Design (brief)](https://github.com/oldhero5/energex/blob/main/docs/2026-06-18-s4-frontend-experience-design.md)

## The through-line

Every stage serves the same invariant: **point-in-time correctness with a visible honesty
boundary.** The store records it (S1), the **live** read API exposes it (S2), the agent
respects it (S3), and the frontend makes it something you can see and feel (S4).
