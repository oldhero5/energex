---
id: roadmap
title: Roadmap
sidebar_label: Roadmap
---

# Roadmap

Energex is built in stages. S1 (the data platform: core, storage, orchestration) is
complete and is what this documentation describes. The remaining stages are reserved in
the package layout and summarized below.

## Focus: power markets

Energex is centered on **power markets**. The **EIA-930 Hourly Electric Grid Monitor**
(demand, day-ahead forecast, net generation, interchange, and generation-by-fuel for all
US balancing authorities) ingests hourly today. **ERCOT** nodal data ingests live from the
ERCOT public API: real-time and day-ahead settlement point prices for the trading hubs and
load zones, plus ERCOT-wide actual system load. Oil & gas and weather remain ingested as
supporting context but are no longer the focus. Next on the power track: additional ISOs
(CAISO, PJM, MISO).

## S2 — Serving (read API)

A FastAPI read API in `energex.service`, with **`as_of` as a first-class parameter on
every endpoint**. This is the single read seam — the place auth and rate-limiting live —
and the only contract the frontend depends on. Indicative surface:

| Endpoint | Returns |
| --- | --- |
| `GET /instruments` | Symbology catalog: what's available, units, revision mode |
| `GET /curve?commodity=&as_of=` | Dated-futures curve as known at `as_of` |
| `GET /term-structure?commodity=&as_of=` | Contango/backwardation + roll yield |
| `GET /volatility?instrument=&method=&as_of=` | Realized / Parkinson / Garman-Klass |
| `GET /fundamentals?series=&as_of=` | EIA/NOAA with vintage + `reconstructed` flag |
| `GET /spot?instrument=&as_of=` | FRED benchmark spot |
| `GET /series/{id}/vintages` | Available knowledge times (drives the time-travel slider) |
| `POST /agent` (stream) | S3 chat; threads `as_of`; returns text + chart payloads |

Every response carries the resolved `as_of` and a `reconstructed: bool`, so consumers
always know which knowledge time they are looking at and whether it is a true or
reconstructed vintage.

## S3 — Agent

A LangGraph analytical agent in `energex.agent`, read-only, that threads `as_of` through
its queries so every answer is point-in-time correct. It calls the S2 API rather than
touching storage directly.

## S4 — Frontend (the commercial product)

The immersive, cross-device application — and the commercial offering — lives in a
**separate, private repository**. It is the paid product; this platform stays
source-available and free for noncommercial use. The two repos are joined only by the S2
read API: neither imports the other, and the app never touches ArcticDB/MinIO directly.

The design north star is an immersive, cinematic experience (WebGL/Three.js,
scroll-driven onboarding) wrapped around an instrument-grade daily "cockpit." The
headline interaction is an **`as_of` time-travel slider** that scrubs through knowledge
time and visibly recolors any series that is a **reconstructed** baseline versus a
**true** forward vintage — making the platform's honesty boundary a tangible product
feature.

The full brief — including the open-core boundary diagram, the responsive-PWA strategy,
the design system, and the milestone plan (freeze the S2 contract → cockpit MVP → PWA
polish → signature 3D + immersive lobby → agent → commercial hardening) — lives in the
repository at `docs/2026-06-18-s4-frontend-experience-design.md`:

- [S4 Frontend Experience Design (brief)](https://github.com/oldhero5/energex/blob/main/docs/2026-06-18-s4-frontend-experience-design.md)

## The through-line

Every stage serves the same invariant: **point-in-time correctness with a visible honesty
boundary.** The store records it (S1), the API exposes it (S2), the agent respects it
(S3), and the frontend makes it something you can see and feel (S4).
