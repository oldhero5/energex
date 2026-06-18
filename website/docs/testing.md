---
id: testing
title: Testing
sidebar_label: Testing
---

# Testing

Energex is tested with `pytest`. The suite covers the pure core (connectors, storage,
quality, symbology, config), the hexagonal boundary, and the Dagster wiring.

## Prerequisites

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/)
- Internet access is **not** required: connector tests mock the HTTP layer with `respx`,
  and storage tests run against a local ArcticDB.

## Running the suite

```bash
uv sync --all-extras                 # install the package with every extra
uv run --all-extras pytest           # full suite (with coverage, per pyproject)
uv run --all-extras pytest -q        # quiet
uv run --all-extras pytest tests/test_storage_pointintime.py   # a single file
```

`arcticdb` must be importable before `pandas`/`pyarrow` (a load-order hazard on macOS);
`tests/conftest.py` already pins this for the whole suite.

## What the suite covers

| Area | Representative tests |
| --- | --- |
| **Hexagonal boundary** | `test_core_has_no_framework_imports`, `test_core_layout` |
| **Storage & point-in-time** | `test_storage_pointintime`, `test_storage_roundtrip`, `test_storage_curve`, `test_latest_is_committed` |
| **Bitemporal invariants** | `test_pointintime_reverse_backfill`, `test_revision_merge_gap`, `test_write_bars_sparse` |
| **Crash safety** | `test_crash_safety` (orphan write + `reconcile_orphans`) |
| **Connectors** | `test_connector_eia`, `test_connector_fred`, `test_connector_weather`, `test_connector_yfinance` |
| **Public API contract** | `test_api_contract` (the importable `energex` public surface, not a data-source connector) |
| **Quality gate** | `test_pandera_schemas`, `test_quality`, `test_quality_collision` |
| **Symbology** | `test_symbology` |
| **Orchestration loads** | `test_definitions_load` (the Dagster `Definitions` import cleanly) |
| **Configuration** | `test_config`, `test_core_config_settings` |
| **Legacy analytics** | `test_volatility`, `test_futures`, `test_dated_futures`, `test_charts`, and others |

### The boundary test is load-bearing

`test_core_has_no_framework_imports` is the executable form of the architecture rule: it
walks every file under `src/energex/core` and fails if any imports `dagster`, `fastapi`,
or `langgraph`. If you accidentally pull a framework into the core, the build goes red.
See [Architecture](./architecture.md#the-core-is-framework-agnostic-and-ci-enforces-it).

### Connector tests

Connector tests use `respx` to stub the source API and assert the shape of the resulting
`FetchResult`: the normalized columns (`instrument_id`, tz-aware-UTC `valid_time`,
`value`), the provenance fields, and `complete_over_range`. No network calls are made.

### Point-in-time and crash-safety tests

These are the most important tests in the project, because they protect the core
invariant. They assert that `read_as_of` never leaks the future, that a reverse backfill
flags `vintage_reconstructed`, that inline revisions merge by exact `valid_time` without
dropping prior rows, and that an orphaned write (a crash between data write and index
append) is invisible to readers and removed by `reconcile_orphans`.

## Linting and formatting

```bash
uv run --all-extras ruff check src/energex tests
uv run --all-extras ruff format --check src/energex tests
```

Install the pre-commit hooks to run these on every commit:

```bash
uv run pre-commit install
```

## Continuous verification

A green checkout should satisfy all of:

- `uv run --all-extras pytest` — the full suite passes.
- `uv run --all-extras ruff check src/energex tests` — no lint errors.
- `uv build` — the wheel builds.
- The Dagster definitions import (`test_definitions_load`), proving the orchestration
  layer is wired and loadable.
