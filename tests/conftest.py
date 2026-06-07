"""Shared pytest fixtures for the energex test suite."""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest


@pytest.fixture
def sample_ohlcv() -> pl.DataFrame:
    """A small, well-formed intraday OHLCV frame for two symbols (1-min bars).

    Timestamps are naive to match the current ``intraday_prices`` schema; the
    UTC-normalization work (ASSESSMENT R5) will migrate this to tz-aware.
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
def tmp_db_path(tmp_path) -> str:
    """An isolated DuckDB file path under tmp — never the repo's energy.db."""
    return str(tmp_path / "test_energy.db")
