---
id: testing
title: Testing
sidebar_label: Testing
---

# Testing

Energex ships with **220+ `pytest` tests** that run **offline by default**. The suite covers
the pure core (connectors, storage, quality gate, symbology, config), the hexagonal
boundary, the S2 read API, and the Dagster wiring. No network, no MinIO, and no
credentials are required to run it.

## The offline invariant

Three seams keep the suite hermetic:

- **Connectors are mocked with `respx`.** Every source HTTP call (EIA-930, ERCOT, FRED,
  EIA v2, NOAA, yfinance) is stubbed at the transport layer, so connector tests assert the
  shape of the resulting `FetchResult` without ever touching the network.
- **Storage runs on LMDB, not MinIO.** The `arctic_uri` fixture hands every storage test a
  unique `lmdb://…` ArcticDB under pytest's `tmp_path`; the live MinIO/S3 backend is never
  contacted.
- **Dagster `Definitions` are validated via the CLI** — the orchestration layer is imported
  and resolved without a running daemon or webserver.

### No credentials, ever

The suite must not read a developer's local `.env`. `tests/conftest.py` enforces this
**before any `energex` import**:

```python
# tests/conftest.py
os.environ["ENERGEX_SKIP_DOTENV"] = "1"
```

With `ENERGEX_SKIP_DOTENV=1`, config never loads the repo-root `.env`, so the offline
no-credentials invariant holds regardless of what keys a developer has set locally. This is
what lets the same tests run identically on a laptop and in CI.

`conftest.py` also pins one load-order hazard: **`arcticdb` is imported before
`pandas`/`pyarrow`** process-wide (an AWS-SDK symbol collision aborts the process on macOS
otherwise). The import is guarded, so test jobs that don't install the `storage` extra can
still collect their non-storage tests; the `arctic_*` fixtures only run when requested.

## Running the suite

```bash
uv sync --all-extras                 # install the package with every extra
uv run --all-extras pytest           # full suite (coverage on, per pyproject)
uv run --all-extras pytest -q        # quiet
uv run --all-extras pytest tests/test_storage_pointintime.py   # a single file
```

`addopts` in `pyproject.toml` turns on coverage by default
(`--cov=energex --cov-report=term-missing`).

## What the suite covers

| Area | Representative tests |
| --- | --- |
| **Hexagonal boundary** | core has zero `dagster` / `fastapi` / `langgraph` imports |
| **Storage & point-in-time** | `test_storage_roundtrip`, `test_storage_pointintime`, `test_latest_is_committed` |
| **Bitemporal invariants** | `test_pointintime_reverse_backfill`, `test_revision_merge_gap`, `test_write_bars_sparse` |
| **Crash safety** | `test_crash_safety` (orphan write + `reconcile_orphans`) |
| **Connectors** | `test_connector_eia`, `test_connector_fred`, `test_connector_weather`, `test_connector_yfinance` |
| **S2 read API** | `test_readapi` (FastAPI endpoint contract, `as_of`, auth, row caps) |
| **Quality gate** | `test_pandera_schemas`, `test_quality_collision`, `test_exceptions` |
| **Symbology** | `test_symbology` (`instrument_id` ↔ `(library, symbol, revision_mode)`) |
| **Orchestration loads** | Dagster `Definitions` resolve via the `dagster` CLI |
| **Configuration** | `test_config`, `test_core_config_settings` |

### The boundary test is load-bearing

The architecture rule — `energex.core` imports no framework — is enforced as an executable
test: it walks every file under `src/energex/core` and fails if any imports `dagster`,
`fastapi`, or `langgraph`. Pull a framework into the core and the build goes red. See
[Architecture](./architecture.md).

### Connector tests

Connector tests use `respx` to stub the source API and assert the shape of the resulting
`FetchResult`: the normalized columns (`instrument_id`, tz-aware-UTC `valid_time`, value
columns), the provenance fields (`source`, `fetched_at`, `source_url`), and
`complete_over_range`. No network calls are made. See
[Data Sources & Connectors](./data-sources-connectors.md).

### Point-in-time and crash-safety tests

These protect the core bitemporal invariant and are the most important tests in the
project. They assert that `read_as_of` never leaks the future, that a reverse backfill flags
`vintage_reconstructed`, that inline revisions merge by exact `valid_time` without dropping
prior rows, and that an orphaned write (a crash between data write and index append) is
invisible to readers and removed by `reconcile_orphans`. See
[Storage & Point-in-Time](./storage-point-in-time.md).

## Linting and formatting

```bash
uv run --all-extras ruff check src/energex tests
uv run --all-extras ruff format --check src/energex tests
```

Ruff is configured in `pyproject.toml` (line length 100; rule sets `E`, `F`, `W`, `I`, `N`,
`UP`, `B`, `A`, `C4`, `T20`). Install the pre-commit hooks to run these on every commit:

```bash
uv run pre-commit install
```

## CI gates

`.github/workflows/ci.yml` runs on every push to `main` and every pull request. A green
checkout must satisfy all of these jobs:

| Job | What it gates |
| --- | --- |
| **Test (pytest)** | Full suite on Python **3.11 and 3.12** (matrix, `fail-fast: false`) |
| **Lint (ruff)** | `ruff check` and `ruff format --check` over `src/energex` and `tests` |
| **Bitemporal storage gate** | The point-in-time / crash-safety / symbology suite on offline LMDB ArcticDB |
| **Pandera quality gate** | `test_pandera_schemas`, `test_quality_collision`, `test_exceptions` |
| **Connector contract gate** | The `respx`-mocked connector tests plus `test_readapi` |
| **Secret scan (gitleaks)** | `gitleaks detect` against `.gitleaks.toml` (redacted) |
| **Docker build** | Builds the image (PRs build-only; push to `main` builds and pushes to GHCR) |
| **Type-check (mypy, advisory)** | `mypy src/energex`, **non-blocking** — emits a warning, never fails the build |

The named gates re-run focused slices of the suite with the minimal extras they need
(`--extra storage`, `--extra quality`, `--extra service`, `--extra dev`), so a regression in
the bitemporal store, the pandera schemas, or the connector contract surfaces as its own red
check rather than buried in the full run.

mypy is **advisory only**: the strict-mypy backlog is being cleared progressively, so the
job emits `::warning::` on errors instead of failing. It flips to a hard gate once clean.

## Continuous verification

Reproduce the CI gates locally before pushing:

```bash
uv run --all-extras pytest                                   # full suite (3.11/3.12 in CI)
uv run --all-extras ruff check src/energex tests             # lint
uv run --all-extras ruff format --check src/energex tests    # format
docker build -t energex:local .                              # image builds
```

See [Deployment](./deployment.md) for what the Docker image runs in production and
[Orchestration](./orchestration.md) for the Dagster assets the suite validates.
