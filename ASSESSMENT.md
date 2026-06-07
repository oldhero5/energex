# Energex — System Decomposition & Improvement Plan

> Assessment of branch `feat/production-upgrade-v0.3.0` (Polars 1.20.0, DuckDB, Python 3.12).
> Produced from a full code audit (every module read + runtime defects reproduced in a sandbox),
> six deep web-research tracks, and a deployment-architecture design for the stated target:
> **run persistently in Docker on OrbStack** (single operator, willing to drop the pip-install model).
> Every "confirmed-by-execution" claim below was reproduced by actually running the code.

---

## 1. Verdict (TL;DR)

`v0.3.0` is a *"production-upgrade" in name only*. It has a polished surface — pydantic-settings
config, a rate limiter, structured-logging module, custom exceptions, an LLM sentiment pipeline, four
analysis modules, Plotly charts — but **almost none of the headline functionality actually runs**, and
the storage layer **destroys all data on every connect**. Two structural truths dominate everything:

1. **The store deletes itself.** `EnergyDatabase.__init__ → _init_tables()` runs `DROP TABLE IF EXISTS intraday_prices` on *every* construction, and `main.py` builds a fresh `EnergyDatabase()` on every run — including the supposedly read-only `--check`. Reproduced: rows before = 1, after = 0. The library's entire purpose (accumulating intraday history) is **impossible** today, and a persistent container would wipe its own volume on boot.

2. **The marquee analytics are dead on arrival.** `VolatilityAnalyzer` (all 3 estimators), `DataQualityChecker` (4 methods), `FuturesAnalyzer` (4 of 5 methods), and `MarketVisualizer` (2 of 4 plots) raise `AttributeError`/`SchemaError`/`ColumnNotFoundError`/`NameError` on first call against Polars 1.20 — they call a nonexistent `GroupBy.mutate()`, aggregate into list dtypes they then compare to scalars, use `.days`/`pl.log` that don't exist, reference an `expiry` column the schema never had, and use numpy without importing it.

Beneath the crashes is a **data-model impossibility**: the store only ever holds three *continuous
front-month proxy* symbols (`CL=F`, `BZ=F`, `NG=F`) with no contract-month/expiry dimension and no spot
leg — so term-structure, roll-yield, basis, and implied-rate analytics are not just buggy but
*structurally meaningless* on the data collected. The "production" controls (timeouts, retries,
`RateLimiter`, `setup_logging`, `cache_ttl`) are **defined but wired into nothing**. There are **no
tests** (`tests/` is empty; `pytest` collects 0) and **no CI gate** (only publish-on-release).

**The good news:** the defects are well-understood and the fixes are mostly mechanical or additive. The
job is to *make data survive → make analytics run → wrap it in a service → then add features*. The
deployment target actually *simplifies* the design: a single long-running container that owns the one
DuckDB writer sidesteps the engine's hardest constraint.

---

## 2. System decomposition

### 2.1 Data flow (today vs. target)

```
TODAY:    yfinance(1d,1m) ─▶ Polars ─▶ DuckDB (DROP+recreate every run) ─▶ [analytics crash] ─▶ Plotly
                                                  ▲ wipes history          news ─▶ LLM ─▶ sentiment (look-ahead leak)

TARGET:   ┌─────────────────────── single container on OrbStack ───────────────────────┐
          │ APScheduler(cron, CME hrs) ─▶ DataSource(adapter) ─▶ Polars ─▶ schema-valid │
          │        idempotent UPSERT ─▶ DuckDB (named volume, TIMESTAMPTZ/UTC) ◀─────────┤
          │ FastAPI (1 writer, read-only readers) ─▶ analytics/vol/futures ─▶ /api + Plotly HTML
          │ news ─▶ structured-output LLM (UTC, embargoed) ─▶ sentiment ─▶ point-in-time join
          └────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Subsystem health

| Subsystem | Status | One-line summary |
|---|---|---|
| **Storage & data model** (`database.py`) | 🔴 broken | `DROP TABLE` on every connect (history loss); delete-then-insert + positional `SELECT *` (silent OHLC corruption on reorder); naive `TIMESTAMP` drops tz; PK upsert unused; no `close()`/context manager. |
| **Ingestion** (`data_fetcher.py`, `main.py`) | 🟠 fragile | Happy path works, but errors swallowed into empty frames (outage ≡ weekend); no timeout/retry/rate-limit despite config; fixed 1-day window snapshotted in `__init__`; yfinance 7-day 1m cap; all status via `print()`. |
| **Volatility** (`analysis/volatility.py`) | 🔴 broken | `GroupBy.mutate()` → `AttributeError`; `.pipe` binds DataFrame to `window_minutes` → `TypeError`; even if fixed, `sqrt(252*1440)` annualization wrong and gaps unmasked. |
| **Data quality** (`analysis/quality.py`) | 🔴 broken | `.mutate()` crash; gap/tick checks aggregate to list dtypes then compare to scalars → `SchemaError`; `.count()` returns a DataFrame not an int; pct-change threshold off by 100×. |
| **Futures** (`analysis/futures.py`) | 🔴 broken | 4/5 methods reference nonexistent `expiry`/`expiry_back`; `.days`/`pl.log` don't exist in Polars 1.20; "term structure"/"basis" are mislabeled inter-commodity spreads (no dated contracts, no spot). |
| **Visualization** (`visualization/charts.py`) | 🔴 broken | `plot_volatility_analysis` crashes twice (`np` never imported; invalid `go.Histogram(weights=...)`); `plot_futures_curve` references `expiry`; mislabeled cross-commodity spreads; zero tests. |
| **LLM sentiment** (`market_sentiment.py`, `news_fetcher.py`, `llm_providers.py`) | 🟠 fragile | Sound shape, but: look-ahead leak (pre-join `dt.truncate` floors news up to ~59 min into the past of a bar), `join_asof` crashes on NewsAPI tz-aware vs naive prices, one bad LLM field aborts the whole batch, dead Reuters "feed" forces the crashing NewsAPI path, **generic headlines triple-counted across all 3 symbols**, regex JSON parsing, unwired rate-limit/TTL, raw scraped text in prompt (injection surface). |
| **Config / logging / errors / rate-limit** (`config.py`, …) | 🟠 fragile | Clean exception hierarchy, but `LLMConfig(env_prefix="")` binds bare `API_KEY`/`MODEL`/`BASE_URL` (confirmed env-collision + secret injection); keys are plain `str` leaking in `repr`; `model_post_init` bypasses validation; `NewsConfig` needs `NEWS_NEWS_API_KEY`; `setup_logging`/`RateLimiter` never called. |
| **Tests / CI / packaging** | 🔴 broken | `tests/` empty → 0 collected; root `test_phase_*.py` are `print`/`sys.exit` scripts outside `testpaths`; only CI is publish-on-release (wrong `uv` PATH, long-lived token); `mypy --strict` currently fails; dev deps not installed; docs/examples crash on copy-paste. |

### 2.3 Verified runtime defects (reproduced in sandbox)

| # | Defect | Proof |
|---|---|---|
| 1 | `EnergyDatabase()` destroys data on init | rows before=1, after=0 (`DATA DESTROYED=True`) |
| 2 | `VolatilityAnalyzer.*` → `AttributeError: no .mutate` | executed on synthetic OHLCV |
| 3 | `DataQualityChecker.check_volume_anomalies/reversals` raise; `check_price_gaps`/`check_tick_quality` → `SchemaError` (list-dtype compare); `.count()` returns DataFrame | executed |
| 4 | `FuturesAnalyzer.*` → `ColumnNotFoundError: 'expiry'`; also `Expr.days` and `pl.log` don't exist | executed |
| 5 | `MarketVisualizer.plot_volatility_analysis` → `NameError: np` | executed |
| 6 | `pytest` collects 0 tests; **dev deps (`pytest`) not even installed in `.venv`** | executed (`ModuleNotFoundError`) |
| + | Timezone: same 09:30-NY bar stored as 14:30 / 06:30 / 23:30 under UTC/LA/Tokyo host TZ | executed (3 values) |
| + | `env_prefix=""` collision: a foreign `API_KEY`/`MODEL` silently injected into `LLMConfig`; `repr` printed `api_key='sk-SUPERSECRET'`; invalid provider accepted | executed |
| + | Shipped examples crash: `fetch_and_store`, `summary['avg_sentiment']`, `settings.database.path` all nonexistent | executed |

---

## 3. Target architecture (persistent Docker service on OrbStack)

**Recommended shape: a single long-running container = one Python process** running FastAPI (uvicorn
`--workers 1`) + an in-process **APScheduler 3.x**, owning the **one** DuckDB read-write connection.

**Why one container, not two:** DuckDB is single-writer-per-file. A second process (even `read_only=True`)
opening `energy.db` while a writer holds it fails with a lock error. So the *correct and simplest*
topology for one operator is a single process that owns the writer and runs both the scheduler and the
API. This also keeps heavy imports (yfinance/polars/duckdb) warm, and avoids the server+worker+Postgres
overhead of Prefect/Dagster (overkill to cron three tickers). API reads use per-thread cursors on the
same connection (DuckDB MVCC gives readers a consistent snapshot while the scheduler writes).

| Concern | Decision |
|---|---|
| **Scheduling** | APScheduler 3.x `BackgroundScheduler`, started/stopped in FastAPI `lifespan`; `CronTrigger(ZoneInfo("America/Chicago"))` gated to CME Globex hours (skip 16:00–17:00 CT break, weekends, holidays); `misfire_grace_time` + `coalesce=True`. 4.0 is pre-release — don't use. |
| **Durability** | Remove `DROP`-on-init; `INSERT … ON CONFLICT` upsert; `TIMESTAMPTZ` + `SET TimeZone='UTC'`; store on a **named Docker volume** (native ext4 in the OrbStack VM) — **never a macOS bind-mount** (VirtioFS advisory-lock/fsync unreliable, DuckDB#13017). `CHECKPOINT` after batches; nightly `EXPORT DATABASE` to a bind-mounted `/backups`. |
| **Serving** | FastAPI + uvicorn (`--workers 1`, **never `--reload`** in-container — the reloader forks a second DB opener). `/healthz` (DB reachable + market-hours-aware `MAX(Datetime)` freshness), JSON endpoints (`/prices`, `/volatility`, `/futures`, `/sentiment`), and HTML chart pages reusing `MarketVisualizer` via `fig.to_html(include_plotlyjs="cdn")`. Skip Streamlit/Dash/Grafana for v1 (each is a second DB opener → needs a Parquet snapshot). Optional Caddy sidecar (`tls internal` + `basicauth`) → `https://energex.orb.local`. |
| **Packaging pivot** | **Keep a slim importable core** (`energex.*`, zero web/scheduler imports) + a thin **`energex.service`** layer (imports core only). Put service deps behind `[project.optional-dependencies] service`. **Demote PyPI**: primary CI artifact becomes a GHCR image; keep `publish.yml` only as a tag-gated/`workflow_dispatch` job (or delete). |

**OrbStack caveats (load-bearing):** the Linux VM (and your containers) run *only while OrbStack runs*
and pause on Mac sleep — ingestion pauses; the overlapping-window upsert self-heals only while the gap
stays under yfinance's ~7-day 1m horizon. For true 24/7: enable OrbStack **"Start at login"**, set
`restart: unless-stopped`, prevent Mac sleep (`caffeinate` / stay plugged in). `restart` acts on
container **exit**, not on `HEALTHCHECK` *unhealthy* — add an `autoheal` sidecar or crash-exit on fatal
conditions. On macOS host restart, containers can be SIGKILLed near-instantly (OrbStack#1897) — the
WAL + `CHECKPOINT` + idempotent upsert + nightly export make a half-written run retry-safe; prefer
"Quit OrbStack" before deliberate reboots.

---

## 4. Prioritized recommendations

Priorities reflect the **critique pass** (some items were re-graded). `P0` = data-loss/crash blocker.
Effort: S < M < L < XL.

### P0 — Stop the bleeding & make it run (days)

- **R1 — Idempotent init + read-only `--check` (S).** Remove `DROP TABLE`; use `CREATE TABLE IF NOT EXISTS`. **`--check` must skip `_init_tables()` entirely** (DDL fails on a `read_only` connection), not merely pass `read_only=True`. Move any reset behind an explicit `--reset`. *Inseparable from R2.*
- **R2 — `ON CONFLICT` upsert with named columns (S).** Delete the per-symbol `DELETE`; `INSERT INTO intraday_prices (Datetime,Symbol,Open,High,Low,Close,Volume) SELECT … ON CONFLICT (Symbol,Datetime) DO UPDATE SET …=excluded.*`. **Validate df columns/dtypes before insert** (a Patito/Pandera assert here would have caught the positional-`SELECT *` OHLC corruption). Pin `duckdb>=1.4.0`. *R1 alone is insufficient — the per-symbol DELETE still wipes history.* **Lock both with one regression test:** insert → re-instantiate against a `/tmp` db → assert COUNT preserved and an overlapping batch merges with no duplicates.
- **R3 — Fix the Polars-1.20 API so analytics run (M–L).** Replace `.group_by('Symbol').mutate([expr])` → `.sort([...]).with_columns(expr.over('Symbol'))` everywhere; rewrite gap/tick checks with `.over('Symbol')` + per-row filter; use `.height`/`select(pl.len()).item()` for scalar counts; fix `calculate_volatility_metrics` (the `.pipe`-binds-DataFrame bug); `import numpy as np` in charts and replace `go.Histogram(weights=…)`; standardize the pct-change units (100× fix). Add tests across all 3 symbols. *(~10 broken methods — re-graded M→M–L.)*
- **R4 — Gate the broken futures/curve API (S).** Until the data model lands (R8), make `expiry`-dependent methods raise a clear `NotImplementedError` and drop them from `__all__`, rather than crashing deep in Polars; remove the bare `except` in example 03. *(Do in Phase 1; not data-loss-urgent so not strictly P0.)*

### P1 — Service spine, correctness floor, safety net (1–3 weeks)

- **R-SVC — Build the `energex.service` layer + Docker/OrbStack deploy (L).** FastAPI app with `lifespan` (open one RW connection → migrate → start/stop APScheduler → `conn.close()` on SIGTERM); `pipeline.py` = fetch→upsert→`CHECKPOINT`→analyze; `/healthz` + result endpoints + Plotly HTML. Multi-stage `uv` Dockerfile (non-root, healthcheck) + `docker-compose.yml` (named volume, `restart: unless-stopped`, `stop_grace_period: 30s`, `init: true`, log rotation). *(See §6 for scaffolding.)*
- **R-SCHED — Idempotent scheduled ingestion (S, paired with R2).** This is the **other half of "accumulate history"** — R2's upsert only builds history if runs recur. Start with APScheduler in-process (or a bare cron/GH-Actions) immediately; defer Prefect/observability.
- **R5 — UTC `TIMESTAMPTZ` normalization (M).** Recreate-and-swap migration to `TIMESTAMPTZ`; `SET TimeZone='UTC'` on connect; `dt.convert_time_zone('UTC')` before insert. Unblocks correct PK dedup and the sentiment join.
- **R6 — Sentiment correctness (M).** Kill the look-ahead leak (don't truncate the join key; keep raw `published_at` UTC + an ingestion-lag embargo); normalize **all** `published_at` to tz-aware UTC (`calendar.timegm` for feedparser); cast both sides before `join_asof`; broaden the normalize `except` to `(TypeError, ValueError, KeyError, …)` so one bad field falls back instead of aborting; `datetime.now(timezone.utc)` for cutoffs; guard the zero-confidence denominator. **Also fix the two root causes the critique surfaced:** the **3× fan-out** (generic headline emitted once per symbol — `_match_symbols` returns all symbols, `_map_sector_to_symbols` is dead) inflating `avg_sentiment`/`news_count`; and the **dead Reuters "feed"** (an HTML page) that forces the crashing NewsAPI-only path — validate `feed.bozo`/`len(entries)` at startup.
- **R6b — Structured outputs + `temperature=0` (S, elevated from R13).** Replace regex/legacy-JSON with provider-native constrained decoding (Anthropic `messages.parse` / OpenAI strict `json_schema`) against a Pydantic `SentimentResult` (Literal enums; still clamp numerics). ~100% schema compliance, eliminates the R6 `TypeError` failure class. `temperature=0` makes sentiment reproducible/backtestable.
- **R9 — Lock down config & secrets (M).** Distinct `env_prefix` (`LLM_`, `DATAFETCH_`); `SecretStr` for all keys (`.get_secret_value()` at use); re-validate overrides (or `validate_assignment=True`); fix `NewsConfig` to the intuitive `NEWS_API_KEY`; document env names incl. `ENERGEX_DB_PATH`.
- **R10 — Wire the "production" controls (M).** Call `setup_logging` once at entry; replace `print()` with structured loggers (structlog: console dev / JSON prod, bound run/symbol context); pass `timeout` + retry/backoff to `yf.download`; wrap LLM/NewsAPI calls in the `RateLimiter` (fix it to release the lock before `sleep`); replace the unbounded dict cache with `TTLCache` (or a DuckDB content-hash cache); emit a per-run summary; **raise `DataFetchError` on real failures** (empty only for genuinely empty). Delete any control you choose not to wire.
- **R11 — Real pytest suite + push/PR CI gate (L).** `tests/unit` + `tests/integration` with fixtures (synthetic OHLCV; `/tmp` DuckDB — never `./energy.db`); mock all network I/O (VCR/`pytest-recording` for yfinance, `responses`/`respx` for HTTP); **Patito/Pandera** OHLCV schema validation + **Hypothesis** property tests for the vol/quality invariants; `ci.yml` on push/PR (matrix 3.10–3.13, `setup-uv`, `uv sync --locked`, ruff + mypy + pytest `--cov-fail-under`). Move `--cov` out of default `addopts` (or install `pytest-cov`); migrate/relocate the root `test_phase_*.py`.

### P2 — Quant correctness, data model, production hardening

- **R7 — Correct the volatility methodology (L).** Realized variance = **sum of squared 5-min log returns** per session (not demeaned `rolling_std`), gap-masked across session boundaries, annualized from actual bars-per-session (or `sqrt(252)` on daily RV); add **Yang-Zhang** (drift/gap-robust) as the headline daily estimator; keep Parkinson/GK on **daily** OHLC (not per-minute). *Elevate the cheap correct-RV slice into Phase 1; leave Yang-Zhang/signature-plot here.*
- **R8 — Real futures data model (XL, decision-gated → re-graded P1→P2).** Multi-contract months + `expiry`/`last_trade` + a spot leg (EIA/FRED) + a risk-free curve; fix sign conventions (backwardation ⇒ positive roll yield), `.dt.total_days()`, ACT/365, `pl.col(...).log()`; rename `calculate_implied_rates` → implied *net carry* `ln(F/S)/T`. **Force the build-vs-cut decision** its own theme names — gating/scoping-out (R4) is a legitimate end state given only continuous proxies exist. **R14 is a prerequisite** (you can't model dated contracts without a source that supplies them) — co-sequence them.
- **R14 — Provider abstraction; move off yfinance (XL, re-graded L→XL).** `DataSource` Protocol; yfinance demoted to an opt-in "personal research" adapter (document the 7-day cap, fail loudly on truncation); Databento GLBX.MDP3 for CL/NG; ICE-licensed vendor for Brent (BZ is **not** on CME Globex); EIA/FRED for the spot leg. Capture license terms in docs.
- **R13 — Harden sentiment quality (L).** FinBERT/FinGPT local fallback (replace keyword heuristic); Batch API + prompt caching + backoff; wrap scraped text as untrusted data (delimiters/spotlighting); build a hand-labeled energy-news gold set (macro-F1) + a point-in-time event-study/IC harness to measure real signal value.
- **R15 — DuckDB ergonomics (M).** Context-managed short-lived writer; `read_only=True` readers; drop the redundant secondary index (PK already indexes `(Symbol,Datetime)`); absolute/configurable `db_path`; document the Parquet/DuckLake scale-out trigger.
- **R16 — Harden packaging & publishing (M).** `[tool.hatch.build.targets.wheel] packages=["src/energex"]` (stop shipping `src/examples`); **OIDC Trusted Publishing** (drop the long-lived token); bump action versions; `gitleaks` in pre-commit + CI.
- **R12 — Fix doc/example API drift (M).** Align package docstring/README/`docs/TESTING.md`/examples to the real API (`EnergyDataFetcher()` + `fetch_all_commodities()` + `db.insert_intraday_data(df)`; `avg_sentiment_by_symbol`; `db_path`); run examples in CI as smoke tests.

### P3 — Cleanup & future

- **R17 — Remove dead/scratch code (S).** Delete `db_startpoint.py` (unguarded NVDA scratch that hits the network and writes `stocks.db` at import); drop the unused `datetime`/`timedelta` import in `volatility.py` and the unreachable `validate_provider`. *Also: partial last-candle flag (upsert can overwrite a final bar with a partial one), Ollama double `is_available()` round-trip, `plot_price_quality` double-renders price, `dict[str, any]` + blanket `type: ignore` defeating strict mypy.*
- **R18 — Document the scale-out path (M).** Record the DuckDB→Parquet/DuckLake trigger and the noise-robust estimator path (two-scale RV → realized kernel) for when sub-5-min precision or concurrent writers are genuinely needed. Not needed now.

---

## 5. Sequenced roadmap

| Phase | Goal | Items | Outcome |
|---|---|---|---|
| **0 — Stop the bleeding** (days) | Data survives | R1 + R2 (+ R17 cleanup) | History accumulates; no self-wipe |
| **1 — Make it run** (~1 wk) | Nothing crashes | R3 (incl. correct-RV slice of R7) + R4 | No public method throws on first call |
| **2 — Service + floor** (~1–3 wks) | Deployable & correct | **R-SVC + R-SCHED** (Docker/OrbStack), R11 (tests+CI, landed *with* the fixes), R5, R9, R10, R6 + R6b | Runs persistently on OrbStack; timestamps unambiguous; sentiment point-in-time correct; regressions blocked |
| **3 — Data model decision** (gated) | Honest futures analytics | R8 **⇄** R14 (co-sequenced) *or* keep R4 gate | Either real multi-contract analytics, or scoped-out cleanly |
| **4 — Hardening** (P2) | Production-grade | R7 (rest), R13, R15, R16, R12 | Licensed data, measured sentiment, secure releases |
| **5 — Scale** (as-needed) | Future | R18 | Parquet/DuckLake + advanced estimators on real need |

**First thing to do** (per the critique): R1 + R2 *together* with the regression test — R1 alone leaves
the per-symbol DELETE wiping history every run.

**Quick wins** (each < ½ day): `CREATE TABLE IF NOT EXISTS` + read-only `--check`; `ON CONFLICT` upsert;
`import numpy as np`; mechanical `.mutate([expr])`→`.with_columns(expr.over('Symbol'))` and `.count()`→`.height`;
`datetime.now(timezone.utc)` cutoffs + broaden the sentiment `except`; `SecretStr` + distinct `env_prefix`;
fix README/examples; delete `db_startpoint.py`; add a no-frills `ci.yml` (ruff+mypy+pytest) even before tests exist.

---

## 6. Concrete scaffolding (from the deployment design)

**Repo layout** — keep core slim, add a thin service layer:

```
src/energex/                # SLIM CORE (no web/scheduler imports; same public API)
  config.py data_fetcher.py database.py news_fetcher.py llm_providers.py
  rate_limiter.py logging_config.py exceptions.py main.py
  analysis/ (quality volatility futures market_sentiment)
  visualization/ (charts → MarketVisualizer reused by service)
  service/                  # NEW (imports core only)
    app.py        # FastAPI + lifespan(open conn, migrate, start/stop scheduler, close conn)
    scheduler.py  # APScheduler CronTrigger (America/Chicago, CME-hours gate)
    routes.py     # /healthz /prices /volatility /futures /sentiment + Plotly HTML
    pipeline.py   # ingest → upsert → CHECKPOINT → analyze
tests/                      # FILL IN: core unit + service /healthz smoke (migrate test_phase_*.py here)
Dockerfile  docker-compose.yml  docker-compose.override.yml  .dockerignore  Caddyfile(opt)
.github/workflows/ci.yml    # NEW primary: uv sync --locked, pytest/ruff/mypy, build+push GHCR
.github/workflows/publish.yml  # DEMOTE to tag-gated / workflow_dispatch
backups/                    # bind-mounted target for nightly EXPORT DATABASE
```

**Dockerfile** (multi-stage `uv`, non-root, PID-1 Python, healthcheck) and **`docker-compose.yml`** (named
volume, `restart: unless-stopped`, `stop_grace_period`, `init: true`, log rotation, optional `autoheal`)
sketches are captured in the deployment-pivot output — `pyproject.toml` adds
`[project.optional-dependencies] service = ["fastapi", "uvicorn[standard]", "apscheduler<4"]`, runtime sets
`ENERGEX_DB_PATH=/data/energy.db`, `TZ=America/Chicago`, and the entrypoint is
`uvicorn energex.service.app:app --host 0.0.0.0 --port 8000 --workers 1` (never `--reload`).

---

## 7. Research appendix — key takeaways & sources

**Market-data sourcing.** yfinance is a personal-research tool (7-day 1m cap, undocumented endpoints, ToS
prohibits automated/commercial use); `CL=F`/`BZ=F`/`NG=F` are *stitched continuous proxies*, not contracts.
Real term-structure needs dated months (`CLF26`…, month codes F–Z) with expiries; Brent is **ICE**, not CME.
Production sources: Databento GLBX.MDP3 (CL/NG), ICE/Refinitiv/Barchart (Brent), EIA/FRED (spot). *Sources:
yfinance#356; databento.com/datasets/GLBX.MDP3; cmegroup.com/datamine; eia.gov/opendata; Yahoo Finance ToS.*

**Storage.** DuckDB is right at this scale (MBs/symbol/year). The two big bugs are architectural: DROP-on-init
and full-symbol delete-then-insert. Fix = `ON CONFLICT … DO UPDATE` on the existing PK; `TIMESTAMPTZ`+UTC;
single-writer/`read_only` readers; `duckdb>=1.4.0` LTS (MERGE, checkpoint vacuuming). Scale-out: Hive-partitioned
Parquet → DuckLake. *Sources: duckdb.org/docs/sql/statements/insert, /connect/concurrency, /2025/09/16 1.4 LTS;
ducklake.select.*

**Volatility.** 1-min RV is microstructure-noise-biased upward — default to ~5-min; RV = **sum of squared
returns** (not demeaned `rolling_std`); `sqrt(252*1440)` is wrong (CME ~23h, gapped) — aggregate to daily RV
then `sqrt(252)`; range estimators (Parkinson/GK/RS/YZ) are **daily** tools; **Yang-Zhang** is the only one
handling overnight gaps. *Sources: Liu-Patton-Sheppard 2015; Hansen-Lunde 2005; Yang-Zhang 2000; Zhang-Mykland-Aït-Sahalia 2005.*

**Futures methodology.** Term structure is cross-sectional across simultaneous dated contracts; cost-of-carry
`F0=S0·e^((r+u-y)T)` → implied *net carry* `ln(F/S)/T` (not "interest rate"); backwardation ⇒ positive roll
yield; basis = spot − futures → 0 at expiry (needs a real spot leg); ACT/365 for carry. *Sources: Hull Ch.5;
CME education (contango/backwardation, roll yield); cmegroup.com/month-codes; EIA OpenData.*

**LLM sentiment.** Use provider-native structured outputs (~100% schema compliance vs ~86%); fix the
point-in-time look-ahead leak and tz crash; FinBERT/FinGPT (~87% F1, local/deterministic) as fallback; batch
+ prompt-cache + rate-limit; treat scraped text as untrusted; evaluate (gold-set macro-F1 + event-study/IC,
out-of-sample to dodge training-cutoff leakage). *Sources: Anthropic & OpenAI structured-outputs docs;
Glasserman-Lin (arXiv:2309.17322); FinGPT (AI4Finance); OWASP prompt-injection cheat sheet.*

**Prod Python.** Stand up pytest (network-mocked via VCR/`responses`, Patito schema validation, Hypothesis
property tests); push/PR CI (ruff+mypy+pytest via `uv`); OIDC Trusted Publishing; structlog; gitleaks; explicit
hatch wheel packaging; APScheduler/cron over Airflow at this scale. *Sources: docs.astral.sh/uv/guides/integration/github;
docs.pypi.org/trusted-publishers; github.com/JakobGM/patito; structlog.org; pypa/gh-action-pypi-publish.*

---

## 8. Top risks

1. **OrbStack isn't always-on** — VM pauses on Mac sleep; the overlapping-window upsert self-heals only within yfinance's ~7-day 1m horizon (add a wider backfill job for longer outages).
2. **Mid-write SIGKILL on host restart** (OrbStack#1897) — mitigated by WAL + `CHECKPOINT` + idempotent upsert + nightly export, not eliminated.
3. **Single-writer rule is load-bearing** — any second container or `--workers >1` opening `energy.db` will lock-error; route extra readers through the JSON API or a Parquet snapshot.
4. **Named volume (not bind-mount) is mandatory** — VirtioFS breaks DuckDB locking/fsync (DuckDB#13017).
5. **Broken analytics + zero tests** mean the service could serve *wrong* results — fix and test before trusting the dashboard, not after.
6. **`include_plotlyjs="cdn"`** needs outbound internet at view time — self-host `plotly.min.js` for a fully offline box.
