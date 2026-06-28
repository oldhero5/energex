---
id: deployment
title: Deployment
sidebar_label: Deployment
---

# Deployment

Energex runs **always-on** on a single host. A Mac Studio on OrbStack is the reference
target, but any Docker host works. The whole platform — power-market ingestion, the
bitemporal ArcticDB store, the Dagster orchestrator, and the S2 read API — is defined in
`docker-compose.yml` and configured from a single `.env`.

## The full stack

```bash
docker compose --profile full up -d
```

| Service | Image | Ports | Role |
| --- | --- | --- | --- |
| `minio` | `quay.io/minio/minio` | 9000, 9001 | ArcticDB object store (S3 API) + web console |
| `minio-init` | `quay.io/minio/mc` | — | One-shot: create the `arctic` bucket + a scoped `arctic-rw` service account |
| `dagster-postgres` | `postgres:16.4` | — | Dagster run / event / schedule storage |
| `dagster-webserver` | `ghcr.io/oldhero5/energex:dagster` | 3000 | Dagster UI |
| `dagster-daemon` | `ghcr.io/oldhero5/energex:dagster` | — | Runs the schedules that ingest every series |
| `api` | `ghcr.io/oldhero5/energex:api` | 8000 | **S2 read API** — `/series`, `/curve`, `/symbols`, `/libraries`, `/healthz` |
| `neo4j` | `neo4j:5.26.0-community` | 7474, 7687 | Optional entity graph (reserved) |

The `api` service is the only contract the separate, private frontend consumes — see
[Frontend integration](./frontend-integration.md). It publishes host port **8000**
(mapped to the container's `8001`) and serves `energex.service.readapi:app` under uvicorn.

A lighter **`dev`** profile brings up just `minio`, `minio-init`, and `dagster-postgres`,
which is everything `uv run dagster dev` needs to drive [orchestration](./orchestration.md)
from your shell while the bitemporal [store](./storage-point-in-time.md) lives in MinIO.

```bash
docker compose --profile dev up -d
uv run dagster dev
```

There is also a `frontend` profile that wires in the private `./frontend` repo (gitignored
here, so the service is inert until that repo is present) and pulls up the `api` plus the
MinIO chain it depends on.

## Built images

Both application images build from this repo's `Dockerfile`, differing only in installed
extras:

- **`ghcr.io/oldhero5/energex:dagster`** — built with `--extra orchestration --extra
  storage --extra quality --extra graph`; shared by `dagster-webserver` and
  `dagster-daemon`.
- **`ghcr.io/oldhero5/energex:api`** — built with `--extra service --extra storage`.

Both run as **`linux/amd64`**. ArcticDB ships no `linux/arm64` wheel, so on M-series Macs
these images execute under emulation — it works, with somewhat slower cold starts. MinIO,
Postgres, and Neo4j run natively.

## Restart policy & logging

Every long-running service sets `restart: unless-stopped`, so the stack recovers on crash
and after a host (or OrbStack) restart. `minio-init` is the exception — it is a one-shot
provisioner with `restart: "no"` (a restart policy would loop it forever). All services
log via the `json-file` driver with rotation (10 MB per file, 5 files), and each carries a
healthcheck plus `mem_limit` / `cpus` caps.

## Persistence

State lives in named Docker volumes — only `docker compose down -v` deletes them:

| Volume | Holds |
| --- | --- |
| `minio-data` | The ArcticDB **store of record** |
| `dagster-pg-data` | Dagster run / event / schedule history |
| `dagster-home` | Shared `DAGSTER_HOME` (instance config + compute logs) |
| `neo4j-data` | The entity graph |

## Configuration: required secrets

Credentials reach the containers via `env_file: .env` and compose `${VAR}` interpolation
at **runtime** — they are never baked into an image, and `.env` is dockerignored. Copy
[`.env.example`](https://github.com/oldhero5/energex/blob/main/.env.example) to `.env` and
fill in real values; the app-side binding lives in `src/energex/core/config.py`.

**`docker-compose.yml` ships no weak built-in defaults for the security-critical secrets.**
These five use the `${VAR:?…}` form, so compose **refuses to start** until each is set in
`.env`:

| Variable | Used by | Purpose |
| --- | --- | --- |
| `MINIO_ROOT_USER` | `minio`, `minio-init` | MinIO root account |
| `MINIO_ROOT_PASSWORD` | `minio`, `minio-init` | MinIO root password |
| `ARCTIC_ACCESS_KEY` | `minio-init`, `api`, dagster | Scoped `arctic-rw` service-account key the app authenticates with (mapped into `MINIO_ACCESS_KEY`) |
| `ARCTIC_SECRET_KEY` | `minio-init`, `api`, dagster | Scoped service-account secret (mapped into `MINIO_SECRET_KEY`) |
| `NEO4J_AUTH` | `neo4j` | Neo4j container auth, in `user/password` form |

`minio-init` uses the MinIO **root** account once to create the bucket and a **scoped**
`arctic-rw` service account from `deploy/minio/arctic-rw.json`. The `api` and Dagster
containers then authenticate with that scoped account (passed through as
`MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`) — never with root. Never commit a real `.env`.

The remaining compose variables fall back to safe non-secret defaults if unset:
`ARCTIC_BUCKET` (`arctic`) and the Dagster Postgres trio `DAGSTER_PG_USERNAME` /
`DAGSTER_PG_PASSWORD` / `DAGSTER_PG_DB`.

## Configuration: connector API keys

The Dagster containers load `.env` so the connectors can authenticate against each source.
See [Data sources & connectors](./data-sources-connectors.md) for what each one ingests.

| Variable | Source | Needed for |
| --- | --- | --- |
| `EIA_API_KEY` | EIA v2 open-data (free) | EIA-930 power series (the primary feed) + EIA fundamentals |
| `ERCOT_USERNAME`, `ERCOT_PASSWORD`, `ERCOT_API_KEY_PRIMARY` | ERCOT public API | ERCOT RT/DA SPP + system load (Azure AD B2C ROPC + APIM subscription key) |
| `FRED_API_KEY` | FRED (St. Louis Fed, free) | WTI / Brent / Henry Hub spot (supporting) |
| `NOAA_TOKEN` | NOAA CDO (optional) | Reserved; the nClimDiv degree-day connector reads public flat files and needs no token |

## S2 read API configuration

The `api` service reads a few optional `ENERGEX_*` variables (all unset by default — see
[`.env.example`](https://github.com/oldhero5/energex/blob/main/.env.example)):

- `ENERGEX_READ_API_KEY` — when set, every data endpoint requires a matching `X-API-Key`
  header; `/healthz` stays open. Unset runs the API open with a startup warning.
- `ENERGEX_CORS_ORIGINS` — comma-separated allow-list (e.g. the frontend origin); unset
  means no cross-origin access.
- `ENERGEX_SERIES_MAX_ROWS` — row cap before an unbounded `/series` read returns `413`
  (narrow the read with `start` / `end` instead).

## In-network addressing

Containers reach MinIO by the compose **service name** (`MINIO_ENDPOINT=minio:9000`), not
`localhost`. The Dagster instance config and workspace are mounted read-only from
`deploy/dagster/dagster.yaml` and `deploy/dagster/workspace.yaml`.

## OrbStack / 24-7 notes

- Enable OrbStack's **"Start at login"** so the stack comes back after a reboot.
- Prevent the Mac from sleeping for true 24/7 operation (`caffeinate`, or keep it plugged
  in with sleep disabled).
- Keep all state on **named Docker volumes**, never macOS bind mounts — VirtioFS is
  unreliable for advisory locks and `fsync`. ArcticDB data lives in MinIO (the
  `minio-data` volume), so it is unaffected.

See [Operations](./operations.md) for backups, GC, and monitoring, and
[Quickstart](./quickstart.md) to bring the stack up for the first time.
