---
id: quickstart
title: Quickstart
sidebar_label: Quickstart
---

# Quickstart

There are two ways to run Energex: the **always-on Docker stack** (the real deployment)
and the **local dev loop** (for working on the code).

## Prerequisites

- Docker / [OrbStack](https://orbstack.dev/) for the always-on stack.
- [`uv`](https://docs.astral.sh/uv/) and Python 3.10+ for the dev loop.
- Two free API keys: [EIA](https://www.eia.gov/opendata/register.php) and
  [FRED](https://fredaccount.stlouisfed.org/apikeys). NOAA and FRED/EIA cover the
  scheduled sources; everything else is optional.

## Run the always-on stack

```bash
cp .env.example .env        # fill in EIA_API_KEY and FRED_API_KEY; placeholders OK for the rest
docker compose --profile full up -d
```

The `full` profile starts:

| Service | Port | What it is |
| --- | --- | --- |
| `dagster-webserver` | 3000 | Dagster UI — assets, schedules, runs, backfills |
| `dagster-daemon` | — | Runs schedules and sensors |
| `dagster-postgres` | — | Dagster instance storage |
| `minio` | 9000 / 9001 | ArcticDB object store + web console |
| `minio-init` | — | One-shot: creates the bucket and scoped service account |
| `neo4j` | 7474 / 7687 | Optional entity graph |
| `energex` | 8000 | Legacy FastAPI service |

Then open:

- **Dagster UI** — http://localhost:3000
- **MinIO console** — http://localhost:9001
- **Neo4j browser** — http://localhost:7474

Four schedules run by default and keep the store current with no manual intervention:

| Schedule | Cadence (ET) | Asset |
| --- | --- | --- |
| EIA gas storage | Thursday 10:35 | `eia_gas_storage` |
| EIA petroleum status | Wednesday 10:35 | `eia_petroleum_status` |
| FRED spot prices | Weekday mornings 09:30 | `fred_spot_prices` |
| NOAA degree days | 6th of the month 12:00 | `noaa_degree_days` |

To verify it is alive, open the Dagster UI and confirm the four schedules show as
running, or trigger a single run manually from the asset graph.

:::note Apple Silicon
ArcticDB has no `arm64` wheel, so the Dagster image is built and run as `linux/amd64`
under emulation. It works on M-series Macs; cold starts are a little slower. See
[Deployment](./deployment.md).
:::

## The dev loop

For working on the code without containers:

```bash
uv sync --all-extras                                       # install with every extra
uv run pytest                                              # run the test suite
uv run ruff check src/energex tests                        # lint
uv run dagster dev -m energex.orchestration.definitions    # local Dagster UI on :3000
```

`uv run dagster dev` still needs a reachable MinIO. The simplest path is to run just the
storage services from compose while you iterate locally:

```bash
docker compose --profile dev up -d minio minio-init dagster-postgres
```

Point your local process at them by setting `MINIO_ENDPOINT=localhost:9000` and the
scoped `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` in `.env` (see
[Configuration in the Deployment guide](./deployment.md#configuration)).

## Next steps

- [Data Sources & Connectors](./data-sources-connectors.md) — what's ingested and how to
  add a new source.
- [Storage & Point-in-Time](./storage-point-in-time.md) — reading vintages with `as_of`.
- [Orchestration](./orchestration.md) — assets, schedules, and backfills in detail.
