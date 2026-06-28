---
id: frontend-integration
title: Frontend Integration (S2 Read API)
sidebar_label: Frontend Integration
---

# Frontend Integration

Energex is **source-available** (PolyForm Noncommercial 1.0.0). This repository is the
power-markets data platform; the polished cross-device **frontend is a separate, PRIVATE
commercial repository**. The two never import each other — the only contract between them
is the **S2 read API** (`energex.service.readapi:app`) documented here.

The S2 read API is a thin, **read-only** FastAPI seam over [`energex.core.storage`](./storage-point-in-time.md).
It is **point-in-time first**: every data endpoint takes an optional `as_of` (ISO datetime)
and defaults to the latest committed vintage when omitted. It opens ArcticDB read-only
using the same URI grammar and credentials as the [orchestration](./orchestration.md) write
side (`MINIO_*` / `ARCTIC_BUCKET` from the environment); the connection URI embeds the S3
secret and is **never logged**.

## The open-core boundary

```
energex (THIS repo)                     energex-app (SEPARATE, PRIVATE repo)
PolyForm Noncommercial (source-avail)   proprietary / commercial
power data platform + S2 read API       the frontend experience (the paid offering)
        │                                          │
        └──────── S2 read API (JSON, as_of) ───────┘
```

- **Decoupled evolution.** The only contract is the S2 read API. This repo owns it; the
  private app consumes it. Neither repo imports the other.
- **Single read seam.** The app NEVER touches ArcticDB/MinIO directly. It only calls S2,
  where auth and CORS live (see below).
- **Point-in-time everywhere.** Every data endpoint accepts an optional `as_of`, which is
  what drives the frontend's time-travel slider.

## Where the API runs

The `api` service in [compose](./deployment.md) runs
`uvicorn energex.service.readapi:app --workers 1`.

| Caller | Base URL |
|---|---|
| In-network (other compose services, e.g. the frontend container) | `http://api:8001` |
| Host / LAN (published port) | `http://<host>:8000` |

The compose `frontend` service is passed `ENERGEX_API_URL=http://api:8001` and depends on
the `api` service. From a browser or a host process, use the published port `:8000`.

## Endpoints

`as_of` is **knowledge time** (when Energex learned a value), not valid time. Omit it for
the latest committed vintage; set it to reconstruct the world as it was known at that
instant. An `as_of` earlier than the first committed vintage returns an empty series and
never leaks the future.

| Method & path | Query params | Returns |
|---|---|---|
| `GET /healthz` | — | `{status, libraries, latest_as_of}` (cheap probe; never auth-gated) |
| `GET /libraries` | — | `["power.lmp", "power.demand", …]` — the ArcticDB libraries present |
| `GET /symbols` | `library` (required) | symbols in a library (the `*__vintages` sidecars are hidden) |
| `GET /series` | `library`, `symbol` (required); `as_of`, `start`, `end` (optional) | `read_as_of` rows as JSON records |
| `GET /curve` | `commodity` (required); `as_of` (optional) | the assembled forward curve as JSON records |

### `GET /healthz`

Cheap liveness/readiness probe. `latest_as_of` is the most recent committed knowledge time
across all symbols, computed by reading only the small `*__vintages` sidecars (never the
heavy series data). This endpoint is **never** auth-gated.

```json
{
  "status": "ok",
  "libraries": ["power.lmp", "power.demand", "power.demand_forecast"],
  "latest_as_of": "2026-06-28T14:00:00"
}
```

### `GET /libraries`

The ArcticDB libraries present, e.g. `power.lmp`, `power.dalmp`, `power.load`,
`power.demand`, `power.demand_forecast`, `power.generation`, `power.interchange`,
`power.generation_by_fuel`, `prices.spot`, `fundamentals.eia`, `weather`.

```json
["power.lmp", "power.dalmp", "power.load", "power.demand"]
```

### `GET /symbols?library=power.lmp`

Symbols in a library. Power symbols are the bare lowercased codes — balancing-authority
codes for EIA-930 (`erco`, `ciso`, …) and settlement-point codes for ERCOT. The internal
`*__vintages` sidecars are filtered out. Returns `404` for an unknown library.

```json
["hb_hubavg", "hb_north", "hb_houston"]
```

### `GET /series?library=…&symbol=…`

The `read_as_of` rows for one symbol as JSON records. Each record carries the `Datetime`
index (the valid time, ISO 8601), the value columns, and the provenance columns including
`vintage_reconstructed` (see [the honesty boundary](#the-reconstructed-vintage-flag)).
`NaN` serializes to `null`.

- `as_of` (optional) — knowledge time; defaults to the latest committed vintage.
- `start`, `end` (optional) — bound the valid-time range. Supplying either makes the read
  a **bounded** read.

Returns `404` for an unknown library or symbol, `400` for an unparseable datetime.

```json
[
  {
    "Datetime": "2026-06-28T13:00:00.000Z",
    "instrument_id": "ERCOT.SPP.HB_HUBAVG",
    "value": 42.17,
    "vintage_reconstructed": false
  }
]
```

#### The full-history row cap (`413`)

An **unbounded** `/series` read (no `start`/`end`) is capped so a single request cannot
serialize an arbitrarily large series into one response. If the result exceeds the cap the
endpoint returns **`413`** with a detail telling you to narrow with `start`/`end`. The cap
defaults to `500000` rows and is configurable via the `ENERGEX_SERIES_MAX_ROWS`
environment variable. **Intentional bounded reads (with `start` and/or `end`) are exempt.**

```json
{ "detail": "series has 812345 rows (> 500000); narrow with start/end" }
```

### `GET /curve?commodity=…`

The assembled forward curve for a commodity as JSON records, optionally `as_of` a past
knowledge time. Returns `404` for an unknown commodity.

### The reconstructed-vintage flag

Every `/series` (and `/curve`) record carries `vintage_reconstructed: bool`. `true` marks
a **reconstructed baseline** (a best-effort backfill, not a true point-in-time forward
vintage); `false` marks a **true** vintage. The flag is per-row, so a series can mix a
reconstructed baseline with later true revisions. The frontend recolors/badges
reconstructed data so the honesty boundary is always visible — never present reconstructed
data as if it were a true forward vintage. See [storage & point-in-time](./storage-point-in-time.md)
for the full bitemporal model.

## Auth (optional API key)

Auth is **opt-in**. When the `ENERGEX_READ_API_KEY` environment variable is set, every
data endpoint (`/libraries`, `/symbols`, `/series`, `/curve`) requires a matching
`X-API-Key` header, compared in constant time. `/healthz` stays open so probes keep
working. When the variable is **unset** the API is open and logs a startup warning. A
missing or invalid key returns **`401`**.

```bash
curl -H "X-API-Key: $ENERGEX_READ_API_KEY" \
  "http://localhost:8000/series?library=power.lmp&symbol=hb_hubavg&start=2026-06-01"
```

## CORS (opt-in, origin-scoped)

Cross-origin access is **opt-in** and origin-scoped. `ENERGEX_CORS_ORIGINS` is a
comma-separated allow-list (e.g. the frontend's origin); only `GET` is allowed. Unset
means no cross-origin access (the safe default).

```bash
ENERGEX_CORS_ORIGINS=https://app.example.com,http://localhost:5173
```

## Example fetches

```bash
# Liveness + latest knowledge time (no key required)
curl http://localhost:8000/healthz

# Discover libraries, then symbols in one
curl http://localhost:8000/libraries
curl "http://localhost:8000/symbols?library=power.lmp"

# A bounded series read (exempt from the 413 cap)
curl "http://localhost:8000/series?library=power.lmp&symbol=hb_hubavg&start=2026-06-01&end=2026-06-28"

# Time-travel: the same series as it was KNOWN at a past instant
curl "http://localhost:8000/series?library=power.demand_forecast&symbol=erco&as_of=2026-06-20T00:00:00"

# Forward curve, as known today
curl "http://localhost:8000/curve?commodity=henryhub"
```

```ts
// From the private frontend (in-network base URL, with the optional key)
const API = process.env.ENERGEX_API_URL ?? "http://api:8001";

async function series(library: string, symbol: string, asOf?: string) {
  const u = new URL(`${API}/series`);
  u.searchParams.set("library", library);
  u.searchParams.set("symbol", symbol);
  if (asOf) u.searchParams.set("as_of", asOf);
  const res = await fetch(u, { headers: { "X-API-Key": process.env.ENERGEX_READ_API_KEY ?? "" } });
  if (res.status === 413) throw new Error("unbounded read too large — pass start/end");
  if (!res.ok) throw new Error(`S2 ${res.status}`);
  return res.json();
}
```

## Running the read-path stack

The frontend lives in a separate private repo. Check it out into `./frontend` (gitignored
here — the compose `frontend` service builds from it and is inert until the repo is
present), then bring up the stack:

```bash
docker compose --profile full up -d
```

This starts MinIO, the Dagster write side, and the `api` (S2 read API) service. The
Dagster operator console (`:3000`) is the operator surface — out of scope for the product.
See [deployment](./deployment.md) and [operations](./operations.md) for the full topology,
and [data sources & connectors](./data-sources-connectors.md) for what fills the libraries.
