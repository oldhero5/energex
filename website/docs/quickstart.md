---
id: quickstart
title: Quickstart
sidebar_label: Quickstart
---

# Quickstart

Energex is a self-hosted, always-on **power-markets** data platform. The whole stack —
the bitemporal ArcticDB store, the Dagster orchestrator that keeps it current, and the
S2 read API the frontend consumes — comes up with **two commands**.

There are two ways to run it: the **always-on Docker stack** (the real deployment) and
the **local dev loop** (for working on the code). See [Architecture](./architecture.md)
for how the pieces fit together.

## Prerequisites

- Docker / [OrbStack](https://orbstack.dev/) for the always-on stack.
- [`uv`](https://docs.astral.sh/uv/) and Python 3.11+ for the dev loop.
- A free [EIA API key](https://www.eia.gov/opendata/register.php) — this alone unlocks
  the primary power feed (EIA-930 demand, forecast, generation, interchange, and
  generation-by-fuel for every US balancing authority).
- A free [FRED API key](https://fredaccount.stlouisfed.org/apikeys) for the supporting
  oil/gas benchmark spot feed.
- ERCOT and NOAA credentials are optional; without them those assets simply stay idle.
  See [Data Sources & Connectors](./data-sources-connectors.md) for every source.

## Run the always-on stack

```bash
git clone https://github.com/oldhero5/energex.git
cd energex
cp .env.example .env
docker compose --profile full up -d
```

Before the second command, open `.env` and fill in the **required** values — compose has
no built-in defaults for these and will refuse to start without them:

| Variable | What it is |
| --- | --- |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | MinIO root (compose-only; provisions the scoped account) |
| `ARCTIC_ACCESS_KEY`, `ARCTIC_SECRET_KEY` | Scoped ArcticDB service account `minio-init` creates |
| `NEO4J_AUTH` | Neo4j container auth, in `user/password` form |
| `EIA_API_KEY` | EIA-930 power feed + gas/crude fundamentals (the primary source) |
| `FRED_API_KEY` | Benchmark spot prices (supporting context) |

Keep `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` in `.env` in sync with the scoped
`ARCTIC_ACCESS_KEY` / `ARCTIC_SECRET_KEY` — the app authenticates with the scoped
account, never the MinIO root. The full annotated list lives in
[`.env.example`](https://github.com/oldhero5/energex/blob/main/.env.example); see
[Deployment](./deployment.md#configuration-required-secrets) for how each variable binds.

### Services the `full` profile starts

| Service | Port | What it is |
| --- | --- | --- |
| `api` | 8000 | **S2 read API** — `/series`, `/curve`, `/symbols`, `/libraries`, `/healthz` |
| `dagster-webserver` | 3000 | Dagster UI — assets, schedules, runs, backfills |
| `dagster-daemon` | — | Runs schedules and sensors |
| `dagster-postgres` | — | Dagster instance storage |
| `minio` | 9000 / 9001 | ArcticDB object store + web console |
| `minio-init` | — | One-shot: creates the bucket and scoped service account |
| `neo4j` | 7474 / 7687 | Optional entity graph |

The `api` service is the **only** contract the separate, private frontend consumes — see
[Frontend Integration](./frontend-integration.md).

### Then open

- **Dagster UI** — http://localhost:3000 (assets, schedules, run history, backfills)
- **MinIO console** — http://localhost:9001 (the ArcticDB object store)
- **Read API (S2)** — http://localhost:8000 (try `GET /healthz`, then `/libraries`)
- **Neo4j browser** — http://localhost:7474 (optional graph)

Schedules ship **running**, so the store stays current with no manual intervention. The
primary power feeds lead the cadence; oil/gas/weather follow as supporting context:

| Schedule | Cadence | Source |
| --- | --- | --- |
| EIA-930 grid monitor | Hourly | Demand, day-ahead forecast, generation, interchange, generation-by-fuel |
| ERCOT RT + load | Hourly (current operating day) | Real-time 15-min SPP and ERCOT-wide load *(needs ERCOT creds)* |
| ERCOT day-ahead | Midday (next operating day) | Day-ahead hourly SPP *(needs ERCOT creds)* |
| FRED spot | Daily (weekday mornings) | WTI / Brent / Henry Hub benchmark spot |
| EIA fundamentals | Weekly (gas Thu, crude Wed) | Lower-48 gas storage, crude stocks ex-SPR |
| NOAA degree days | Monthly | HDD/CDD by US region |

To verify it is alive, open the Dagster UI and confirm the schedules show as running, or
trigger a single asset run from the asset graph and watch it land in MinIO. Full detail
in [Orchestration](./orchestration.md) and
[Storage & Point-in-Time](./storage-point-in-time.md).

:::note Apple Silicon
ArcticDB has no `arm64` wheel, so the Dagster and `api` images are built and run as
`linux/amd64` under emulation. It works on M-series Macs; cold starts are a little
slower. See [Deployment](./deployment.md).
:::

## The dev loop

For working on the code without containers:

```bash
uv sync --all-extras                                       # install with every extra
uv run pytest                                              # run the test suite
uv run ruff check src/energex tests                        # lint
uv run dagster dev -m energex.orchestration.definitions    # local Dagster UI on :3000
```

The test suite runs **offline** by default (connectors mocked, storage on LMDB), so
`uv run pytest` needs nothing running. See [Testing](./testing.md).

`uv run dagster dev`, however, still needs a reachable MinIO. The lighter `dev` profile
brings up just the storage services so you can iterate locally:

```bash
docker compose --profile dev up -d   # minio + minio-init + dagster-postgres
```

Point your local process at them by setting `MINIO_ENDPOINT=localhost:9000` and the
scoped `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` in `.env` (see
[Configuration in the Deployment guide](./deployment.md#configuration-required-secrets)).

## Next steps

- [Data Sources & Connectors](./data-sources-connectors.md) — what's ingested and how to
  add a new source.
- [Storage & Point-in-Time](./storage-point-in-time.md) — reading vintages with `as_of`.
- [Orchestration](./orchestration.md) — assets, schedules, and backfills in detail.
- [Frontend Integration](./frontend-integration.md) — consuming the S2 read API.
