"""Shared pytest fixtures for the energex test suite."""

from __future__ import annotations

import os

# Set BEFORE any energex import: the suite must not load the repo-root .env, so the offline
# no-credentials invariant holds regardless of a developer's local .env.
os.environ["ENERGEX_SKIP_DOTENV"] = "1"

from datetime import date, datetime, timedelta, timezone  # noqa: E402

# NOTE: arcticdb MUST be imported before pandas/pyarrow process-wide (phase0 findings:
# AWS-SDK symbol collision aborts the process on macOS otherwise). conftest loads before
# any test module, so importing it here pins the load order for the whole suite.
# Guarded so test jobs that don't install the `storage` extra (e.g. the quality gate)
# can still collect their non-storage tests; the arctic_* fixtures only run when requested.
try:
    import arcticdb  # noqa: F401
except ImportError:
    arcticdb = None  # type: ignore[assignment]

import polars as pl
import pytest


@pytest.fixture
def sample_ohlcv() -> pl.DataFrame:
    """A small, well-formed intraday OHLCV frame for two symbols (1-min bars).

    Timestamps are naive to match the current ``intraday_prices`` schema; later
    UTC-normalization work will migrate this to tz-aware.
    """
    base = datetime(2024, 1, 2, 14, 30)
    rows = []
    for sym, p0 in (("CL=F", 75.0), ("NG=F", 2.5)):
        for i in range(30):
            px = p0 + i * 0.1
            rows.append(
                {
                    "Datetime": base + timedelta(minutes=i),
                    "Symbol": sym,
                    "Open": px,
                    "High": px + 0.2,
                    "Low": px - 0.2,
                    "Close": px + 0.05,
                    "Volume": 1000 + i * 10,
                }
            )
    return pl.DataFrame(rows)


@pytest.fixture
def sample_daily_contracts() -> pl.DataFrame:
    """Dated-contract daily settlements for two commodities over two snapshot days.

    ``crude`` is backwardated (near > far); ``gas`` is contango (near < far). Datetimes
    are tz-aware UTC; ContractMonth is the first of the delivery month.
    """
    rows = []
    snapshots = [
        datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc),
        datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc),
    ]
    # (commodity, root, base price, per-month step) — negative step = backwardation.
    specs = [
        ("crude", "CL", 80.0, -0.5),
        ("gas", "NG", 2.0, 0.05),
    ]
    month_codes = "FGHJKMNQUVXZ"
    for snap_i, snap in enumerate(snapshots):
        for commodity, root, base, step in specs:
            for m in range(6):
                contract_month = date(2024, 2 + m, 1)
                close = base + step * m + snap_i * 0.1
                rows.append(
                    {
                        "Datetime": snap,
                        "Commodity": commodity,
                        "ContractMonth": contract_month,
                        "Symbol": f"{root}{month_codes[1 + m]}24.NYM",
                        "Open": close - 0.1,
                        "High": close + 0.2,
                        "Low": close - 0.2,
                        "Close": close,
                        "Volume": 1000 + m * 10,
                        "OpenInterest": 5000 + m * 100,
                    }
                )
    return pl.DataFrame(rows)


@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    """An isolated DuckDB file path under tmp — never the repo's energy.db."""
    return str(tmp_path / "test_energy.db")


@pytest.fixture
def arctic_uri(tmp_path) -> str:
    """A unique, offline LMDB-backed ArcticDB URI under pytest's tmp (no MinIO)."""
    return f"lmdb://{tmp_path / 'energex-test-arctic'}"


@pytest.fixture
def arctic_store(arctic_uri):
    """A fresh, isolated ArcticDB instance; LMDB files vacated with tmp_path."""
    import arcticdb as adb

    return adb.Arctic(arctic_uri)


@pytest.fixture
def arctic_lib(arctic_store):
    """A single throwaway library; storage functions take the Library object directly."""
    return arctic_store.create_library("phase2")


@pytest.fixture
def observer_arctic(arctic_store, arctic_uri, monkeypatch):
    """LMDB-backed ArcticDB instance monkeypatched into energex.observer.arctic.get_arctic.

    Creates the ``power.load`` library used by observer metadata tests.
    The test may create additional libraries via ``arctic_store`` if needed.
    """
    monkeypatch.setenv("ENERGEX_ARCTIC_URI", arctic_uri)
    arctic_store.create_library("power.load")

    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    return arctic_store
