---
id: frontend-integration
title: Frontend Integration (S2 Read API)
sidebar_label: Frontend Integration
---

# Frontend Integration

Energex is **open-core**. This repository is the noncommercial data platform; the
polished cross-device **frontend is a separate, PRIVATE commercial repository**. The two
never import each other — the only contract between them is the **S2 read API** defined
here. Freeze this contract before frontend work begins.

See the design brief [`docs/2026-06-18-s4-frontend-experience-design.md`](https://github.com/oldhero5/energex/blob/main/docs/2026-06-18-s4-frontend-experience-design.md)
for the product vision (the cinematic lobby, the instrument-grade cockpit, and the
headline `as_of` time-travel slider).

## The open-core boundary

```
energex (THIS repo)                     energex-app (SEPARATE, PRIVATE repo)
PolyForm Noncommercial (source-avail)   proprietary / commercial
data platform + analytics + S2 API      the frontend experience (the paid offering)
        │                                          │
        └──────── S2 read API (JSON, as_of) ───────┘
```

- **Open-core monetization.** The platform stays free for individuals; the app is the
  paid product, with no license friction between them.
- **Decoupled evolution.** The only contract is the S2 read API. This repo owns and
  freezes it; the private app consumes it. Neither repo imports the other.
- **Security.** The app NEVER touches ArcticDB/MinIO directly. It only calls S2, which is
  the single read seam and the place auth/rate-limiting will live.

## The read API contract

The S2 read API (`energex.service.readapi:app`) is a thin, **read-only** FastAPI app over
`energex.core.storage`. It opens ArcticDB read-only using the same URI grammar and
credentials as the orchestration write side (`MINIO_*` / `ARCTIC_BUCKET` from the
environment); the connection URI embeds the S3 secret and is never logged.

`as_of` is first-class: every data endpoint accepts an **optional** `as_of` ISO datetime
query parameter and defaults to the **latest committed vintage** when omitted.

| Method & path | Query params | Returns |
|---|---|---|
| `GET /healthz` | — | `{status, libraries, latest_as_of}` (cheap probe) |
| `GET /libraries` | — | the ArcticDB libraries present |
| `GET /symbols` | `library` | symbols in a library (the `*__vintages` sidecars are hidden) |
| `GET /series` | `library`, `symbol`, `as_of?`, `start?`, `end?` | `read_as_of` rows as JSON records |
| `GET /curve` | `commodity`, `as_of?` | the assembled forward curve as JSON records |

### `as_of` semantics

`as_of` is **knowledge time** (when something became known), not valid time. With
`as_of` omitted you get the latest committed vintage. With `as_of` set you get the world
**as it was known at that instant** — earlier than the first committed vintage returns an
empty series. This is what drives the frontend's time-travel slider.

### The reconstructed-vintage flag (the honesty boundary)

Every `/series` (and `/curve`) record carries `vintage_reconstructed: bool`. `true` marks
a **reconstructed baseline** (a best-effort backfill, not a true point-in-time forward
vintage); `false` marks a **true** vintage. The flag is per-row, so a series can mix a
reconstructed baseline with later true revisions — the frontend recolors/badges
reconstructed data so the honesty boundary is always visible. Never present reconstructed
data as if it were a true forward vintage.

## Running the frontend with the platform

The frontend lives in a separate private repo. Check it out into `./frontend` (this path
is **gitignored** in this repo — the compose `frontend` service builds from it and is
inert until the repo is present):

```bash
# from the repo root
git clone git@github.com:<org>/energex-app.git frontend
```

The compose `frontend` service passes `ENERGEX_API_URL=http://api:8001` (the in-network
S2 read API) and depends on the `api` service. Bring up the read-path stack (MinIO + the
S2 API + the frontend):

```bash
docker compose --profile frontend up
```

This starts `minio`, `minio-init`, `api`, and `frontend`. To also run the write side
(Dagster ingestion) use the full stack:

```bash
docker compose --profile full up
```

The Dagster operator console (`:3000`) is **not** part of the product — it is the
operator surface, out of scope for the frontend.
