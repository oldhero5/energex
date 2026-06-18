# Contributing to Energex

Thanks for your interest in Energex. This guide covers the local dev setup, the
quality bar, and the one architectural rule that the CI enforces.

## Development setup

Energex uses [`uv`](https://docs.astral.sh/uv/) for environment and dependency
management.

```bash
git clone https://github.com/oldhero5/energex.git
cd energex
uv sync --all-extras        # install the package with every optional extra
```

The full ingestion stack (MinIO, Dagster, Neo4j) runs under Docker / OrbStack:

```bash
cp .env.example .env        # fill in EIA_API_KEY and FRED_API_KEY (both free)
docker compose --profile full up -d
```

For a local Dagster UI without containers:

```bash
uv run dagster dev -m energex.orchestration.definitions   # http://localhost:3000
```

## Tests

```bash
uv run --all-extras pytest          # full suite
uv run --all-extras pytest -q       # quiet
```

Please add tests for any new behavior. Connector, storage, and point-in-time
correctness changes in particular must come with tests — the bitemporal invariants
are the heart of the project. See the [Testing guide](website/docs/testing.md) for the
suite layout and what each area covers.

## Linting and formatting

```bash
uv run ruff check src/energex tests     # lint
uv run ruff format src/energex tests    # format
```

Install the pre-commit hooks so this runs automatically on every commit:

```bash
uv run pre-commit install
```

## The core/framework boundary (please read)

Energex is hexagonal. The domain core, **`energex.core`**, is pure and must never
import an application framework. Only `energex.orchestration` may import Dagster
(and, when they land, `energex.service` may import FastAPI, `energex.agent` LangGraph).

This is enforced by `tests/test_core_has_no_framework_imports.py`, which walks every
file under `src/energex/core` and fails the build if it finds an import of `dagster`,
`fastapi`, or `langgraph`. Keep business logic and storage in the core; keep framework
glue in the layer that owns it.

When adding a data source, implement the `Connector` protocol
(`energex.core.connectors.base`) and route its instruments through
`energex.core.symbology` — see
[Data Sources & Connectors](website/docs/data-sources-connectors.md).

## Licensing and contributions

Energex is source-available under the
[PolyForm Noncommercial License 1.0.0](LICENSE). By contributing, you agree that your
contributions are provided under that same license.

Energex follows an open-core model: a separate, private commercial product builds on
this platform's read API. Because of that, **a Contributor License Agreement (CLA) will
be required before any outside contribution can be accepted into the commercial
product.** We will ask you to sign the CLA on your first non-trivial pull request.

If you are unsure whether a change fits, open an issue first to discuss it.
