---
id: deployment
title: Deployment
sidebar_label: Deployment
---

# Deployment

Energex is designed to run **always-on** on a single host — a Mac Studio on OrbStack is
the reference target, but any Docker host works. Everything is defined in
`docker-compose.yml`.

## The full stack

```bash
docker compose --profile full up -d
```

| Service | Image | Ports | Role |
| --- | --- | --- | --- |
| `minio` | MinIO | 9000, 9001 | ArcticDB object store + console |
| `minio-init` | MinIO `mc` | — | One-shot: create bucket + scoped service account |
| `dagster-postgres` | Postgres 16 | — | Dagster instance storage |
| `dagster-webserver` | Energex (amd64) | 3000 | Dagster UI |
| `dagster-daemon` | Energex (amd64) | — | Runs schedules/sensors |
| `neo4j` | Neo4j 5 Community | 7474, 7687 | Optional entity graph |
| `energex` | Energex | 8000 | Legacy FastAPI service |

A lighter `dev` profile brings up just MinIO, `minio-init`, and `dagster-postgres` for
local iteration with `uv run dagster dev`.

All services set `restart: unless-stopped`, so they recover on crash and when the host
(or OrbStack) restarts. Logs use the `json-file` driver with rotation (10 MB per file,
5 files).

## Persistence

State lives in named Docker volumes (only `docker compose down -v` deletes them):

| Volume | Holds |
| --- | --- |
| `minio-data` | The ArcticDB **store of record** |
| `dagster-pg-data` | Dagster run/event/schedule history |
| `dagster-home` | Dagster instance config + compute logs |
| `neo4j-data` | The entity graph |
| `energex-data` | The legacy service's DuckDB file |

## Secrets

Credentials are provided to containers via `env_file: .env` at **runtime** — they are
never baked into the image, and `.env` is dockerignored. `minio-init` uses the MinIO root
account to create a **scoped** `arctic-rw` service account (from
`deploy/minio/arctic-rw.json`); the Dagster containers authenticate with that scoped
account, not root. Never commit a real `.env`.

## Apple Silicon: the amd64 note

ArcticDB ships no `linux/arm64` wheel. The Dagster webserver and daemon images are
therefore built and run as **`linux/amd64`** and execute under emulation on M-series
Macs. It works; expect somewhat slower cold starts. The other services run natively.

## OrbStack / 24-7 notes

- Enable OrbStack's **"Start at login"** so the stack comes back after a reboot.
- Prevent the Mac from sleeping for true 24/7 operation (`caffeinate`, or keep it
  plugged in with sleep disabled).
- **Do not** place the legacy `energy.db` on a macOS bind mount — VirtioFS breaks
  DuckDB's advisory locks and `fsync` (DuckDB issue #13017). It lives on the native
  `energex-data` volume for exactly this reason. ArcticDB data lives in MinIO, not on a
  bind mount, so it is unaffected.

## Configuration

All configuration is environment-driven and documented in
[`.env.example`](https://github.com/oldhero5/energex/blob/main/.env.example); the binding
lives in `src/energex/core/config.py`. The essentials:

| Variable | Purpose |
| --- | --- |
| `MINIO_ENDPOINT` | `host:port` of MinIO. `localhost:9000` locally; `minio:9000` inside the compose network |
| `ARCTIC_BUCKET`, `ARCTIC_SECURE` | ArcticDB bucket and TLS toggle |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | Scoped ArcticDB service-account credentials the app uses |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | MinIO root (compose-only; provisions the scoped account) |
| `ARCTIC_ACCESS_KEY`, `ARCTIC_SECRET_KEY` | Scoped account `minio-init` creates (mapped into the app's `MINIO_ACCESS_KEY`/`SECRET_KEY`) |
| `EIA_API_KEY`, `FRED_API_KEY`, `NOAA_TOKEN` | Source connector credentials |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_AUTH` | Entity graph |
| `DAGSTER_PG_USERNAME`, `DAGSTER_PG_PASSWORD`, `DAGSTER_PG_DB` | Dagster Postgres |
| `ENERGEX_DB_PATH`, `TZ`, `ENERGEX_INGEST_CRON` | Legacy service |

Containers reach MinIO by the compose **service name** (`minio:9000`), not `localhost`.
The Dagster instance config and workspace are mounted read-only from
`deploy/dagster/dagster.yaml` and `deploy/dagster/workspace.yaml`.

See [Operations](./operations.md) for backups, GC, and monitoring.
