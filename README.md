# Energex

A self-hosted, always-on energy-market data platform with a **bitemporal
(point-in-time-correct) store of record**.

Energex continuously ingests public energy data — EIA fundamentals, NOAA weather,
FRED benchmark spot prices, and (in development) intraday futures — validates every
batch through a quality gate, and commits it to a versioned ArcticDB store on MinIO.
The store remembers not just *what* a value was, but *when each value became known*,
so you can reconstruct exactly what the data looked like at any past moment.

## Why point-in-time matters

Government and market data is **revised**. EIA restates gas-storage and crude-stock
figures for weeks after first publication; NOAA reissues monthly degree-day files.
A naive store overwrites the old number and silently rewrites history — which makes
any backtest run against it optimistic and wrong.

Energex keeps two independent time axes on every observation:

- **`valid_time`** — the period the row describes (e.g. the week ending 2026-05-30).
- **`as_of`** — the knowledge/release time: *when we learned this value.*

`read_as_of(symbol, as_of=T)` returns the data exactly as it was known at time `T` —
no future leakage. Because upstream sources (EIA, ERCOT) revise inline and expose no
vintage parameter, **true** point-in-time history can only accrue going forward, from
the day Energex starts watching. History captured by backfilling is flagged
`vintage_reconstructed=True` so a backtest never mistakes a reconstructed baseline for
something that was actually observed at the time. That honesty flag is the platform's
core invariant.

## Architecture

Energex uses a **hexagonal (ports-and-adapters)** layout. The domain core is pure and
framework-agnostic; orchestration is the only layer allowed to import a framework
(Dagster). A CI test (`tests/test_core_has_no_framework_imports.py`) fails the build if
`energex.core` ever imports `dagster`, `fastapi`, or `langgraph`.

| Layer | Package | Responsibility |
| --- | --- | --- |
| **Core** (pure) | `energex.core` | Connectors (`Connector` protocol + `FetchResult`), storage (ArcticDB bitemporal store), quality gate (pandera), symbology, schemas, config. Zero framework imports. |
| **Orchestration** | `energex.orchestration` | The only Dagster importer: assets, checks, partitions, schedules, resources, reconcile, definitions. |
| **Serving** *(reserved, S2)* | `energex.service` | FastAPI read API with `as_of` as a first-class parameter. |
| **Agent** *(reserved, S3)* | `energex.agent` | LangGraph analytical agent over the read API. |

The **S4 frontend** (the immersive cross-device app) lives in a **separate private
repository** and is the commercial product. It consumes only the S2 read API — that is
the open-core boundary. See the
[frontend design brief](docs/2026-06-18-s4-frontend-experience-design.md) and the
[roadmap](website/docs/roadmap.md).

```
sources ──> Connector ──> quality gate ──> ArcticDB (MinIO)
(EIA/NOAA/    (core)        (pandera)        bitemporal store of record
 FRED/yf)                                          │
                                                   ▼
                              Dagster (assets · schedules · checks · reconcile)
```

## Live data sources

| Source | Connector | ArcticDB library | Cadence | Revision mode |
| --- | --- | --- | --- | --- |
| **EIA v2** fundamentals (Lower-48 gas storage, crude stocks ex-SPR) | `EiaGasStorageConnector`, `EiaPetroleumStatusConnector` | `fundamentals.eia` | Weekly (Thu / Wed) | `bitemporal_merge` |
| **NOAA nClimDiv** (HDD/CDD by US region) | `NOAANClimDivConnector` | `weather` | Monthly | `bitemporal_replace` |
| **FRED** benchmark spot (WTI, Brent, Henry Hub) | `FredConnector` | `prices.spot` | Daily (weekdays) | `degenerate` |
| **yfinance** front-month intraday (CL/BZ/NG) | `YFinanceIntradayConnector` | `prices.intraday` | Manual — **dev only** | `degenerate` |

> **yfinance is dev-only and unscheduled.** Yahoo frequently blocks programmatic
> access, so a schedule would only fire failing runs. The asset stays manual.

An optional **Neo4j** entity graph references these instruments by symbol but never
owns the numbers.

## Quickstart

### Run the always-on stack

Requires Docker / OrbStack. The `full` profile brings up MinIO, Dagster (Postgres +
webserver + daemon), Neo4j, and the S2 read API.

```bash
cp .env.example .env        # fill in EIA_API_KEY and FRED_API_KEY (free); placeholders OK for the rest
docker compose --profile full up -d
```

Then open:

- **Dagster UI** — http://localhost:3000 (assets, schedules, run history, backfills)
- **MinIO console** — http://localhost:9001 (the ArcticDB object store)
- **Neo4j browser** — http://localhost:7474
- **Legacy API** — http://localhost:8000

Four schedules run by default and keep the store current with no manual intervention:
EIA gas storage (Thursday), EIA petroleum status (Wednesday), FRED spot (weekday
mornings), and NOAA degree days (monthly).

> **Apple Silicon note:** ArcticDB has no `arm64` wheel, so the Dagster image is built
> and run as `linux/amd64` under emulation. It works on M-series Macs; expect slightly
> slower cold starts.

### Dev loop

```bash
uv sync --all-extras                                   # install everything
uv run pytest                                          # run the test suite
uv run ruff check src/energex tests                    # lint
uv run dagster dev -m energex.orchestration.definitions  # local Dagster UI on :3000
```

## Configuration

All configuration is environment-driven. Copy [`.env.example`](.env.example) to `.env`
and fill in real values (the live `.env` is gitignored — never commit secrets).

Key variables (see [`.env.example`](.env.example) for the complete annotated list and
[`src/energex/core/config.py`](src/energex/core/config.py) for how they bind):

| Variable | Purpose |
| --- | --- |
| `MINIO_ENDPOINT`, `ARCTIC_BUCKET`, `ARCTIC_SECURE` | ArcticDB-on-MinIO connection |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | Scoped ArcticDB service-account credentials |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | MinIO root (compose-only; provisions the scoped account) |
| `ARCTIC_ACCESS_KEY`, `ARCTIC_SECRET_KEY` | Scoped service account created by `minio-init` |
| `EIA_API_KEY`, `FRED_API_KEY`, `NOAA_TOKEN` | Source connector credentials |
| `ERCOT_USERNAME`, `ERCOT_PASSWORD`, `ERCOT_SUBSCRIPTION_KEY` | ERCOT credentials (reserved) |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Entity graph |
| `DAGSTER_PG_USERNAME`, `DAGSTER_PG_PASSWORD`, `DAGSTER_PG_DB` | Dagster Postgres (compose) |
| `DEFAULT_LLM_PROVIDER`, `DEFAULT_LLM_MODEL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_BASE_URL` | LLM provider (reserved, S3) |
| `LOG_LEVEL`, `LOG_FILE`, `LOG_ENABLE_CONSOLE` | Logging |

## How point-in-time works

Each connector returns a `FetchResult` whose frame carries an `instrument_id`, a
tz-aware UTC `valid_time`, value columns, and provenance (`source`, `fetched_at`,
`source_url`). Every batch is validated by the pandera quality gate *before* any write.

The store then commits according to the instrument's **revision mode**:

- **`degenerate`** — never-revised streams (FRED spot, intraday bars). `write_bars`
  appends with de-duplication; `as_of` equals `fetched_at`.
- **`bitemporal_replace`** — each release is a complete as-known series (NOAA). A full
  versioned write per `as_of`.
- **`bitemporal_merge`** — each release revises a window inline (EIA). Read-modify-write
  merges the revision window onto the prior as-known series, by exact `valid_time`.

Vintages are addressed through an append-only, per-symbol integer version index. The
index append is the atomic **commit point**: a crash between the data write and the
index append leaves an orphan data version, which `reconcile_orphans` cleans up.
`read_as_of` always resolves against the *committed* index, never an orphan.

Full walkthrough: see the [documentation site](website/docs/intro.md), in particular
[Storage & Point-in-Time](website/docs/storage-point-in-time.md).

## Documentation

A complete Docusaurus documentation site lives in [`website/`](website):

```bash
cd website
npm install
npm run start     # local dev server with live reload
npm run build     # production build into website/build
```

It covers the architecture, bitemporal model, quickstart, data sources & connectors,
storage internals, orchestration, deployment, operations, testing, and the roadmap.

## Roadmap

- **S2 — Serving:** FastAPI read API with `as_of` first-class on every endpoint
  (`/curve`, `/term-structure`, `/fundamentals`, `/spot`, `/series/{id}/vintages`).
- **S3 — Agent:** LangGraph analytical agent that threads `as_of` through read-only
  queries.
- **S4 — Frontend:** the immersive cross-device app (separate private repo, the
  commercial product), consuming only the S2 API. See the
  [frontend brief](docs/2026-06-18-s4-frontend-experience-design.md).

## Contributing

Contributions are welcome — please read [CONTRIBUTING.md](CONTRIBUTING.md) for the dev
setup, the core/framework boundary rule, and licensing terms.

## License

Energex is **source-available** under the [PolyForm Noncommercial License 1.0.0](LICENSE).

- **Free** for noncommercial use — personal, research, educational, hobby, nonprofit, and government.
- **Commercial use requires a paid license.** A commercial offering is in development; contact <oldhero5@proton.me> for commercial licensing.
- If you use Energex in published, academic, or research work, please **cite it** — see [CITATION.cff](CITATION.cff).

> This is a *source-available* license, not an OSI-approved "open source" license, because it restricts commercial use. Versions previously released under the MIT License remain available under MIT.
