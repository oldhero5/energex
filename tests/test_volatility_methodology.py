"""Tests for the corrected volatility estimators (R7)."""

import math
from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from energex.analysis.volatility import VolatilityAnalyzer

UTC = timezone.utc


def _intraday(symbol: str, day: datetime, closes: list[float]) -> list[dict]:
    base = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)
    return [
        {
            "Datetime": base + timedelta(minutes=i),
            "Symbol": symbol,
            "Open": c,
            "High": c + 0.5,
            "Low": c - 0.5,
            "Close": c,
            "Volume": 100,
        }
        for i, c in enumerate(closes)
    ]


def test_realized_variance_is_sum_of_squared_intraday_returns():
    closes = [100.0, 101.0, 100.0, 102.0]
    df = pl.DataFrame(_intraday("CL=F", datetime(2024, 1, 2), closes))
    out = VolatilityAnalyzer(df).realized_volatility_daily()
    rets = [math.log(101 / 100), math.log(100 / 101), math.log(102 / 100)]
    expected = sum(r * r for r in rets)
    assert out["realized_variance"][0] == pytest.approx(expected)
    assert out["realized_vol_annual"][0] == pytest.approx(math.sqrt(expected) * math.sqrt(252))


def test_overnight_return_is_masked():
    rows = _intraday("CL=F", datetime(2024, 1, 2), [100.0, 101.0])
    rows += _intraday("CL=F", datetime(2024, 1, 3), [200.0, 202.0])  # big overnight jump
    out = VolatilityAnalyzer(pl.DataFrame(rows)).realized_volatility_daily()
    day2 = out.filter(pl.col("date") == datetime(2024, 1, 3).date())
    # Only the intraday ln(202/200) counts — not the overnight ln(200/101).
    assert day2["realized_variance"][0] == pytest.approx(math.log(202 / 200) ** 2)


def test_to_daily_ohlc_aggregates_correctly():
    df = pl.DataFrame(_intraday("CL=F", datetime(2024, 1, 2), [100.0, 105.0, 95.0, 102.0]))
    daily = VolatilityAnalyzer(df).to_daily_ohlc()
    assert daily.height == 1
    row = daily.row(0, named=True)
    assert row["Open"] == 100.0
    assert row["High"] == 105.5
    assert row["Low"] == 94.5
    assert row["Close"] == 102.0
    assert row["Volume"] == 400


def test_yang_zhang_runs_and_is_positive():
    rows: list[dict] = []
    for d in range(2, 8):  # 6 trading days
        rows += _intraday("CL=F", datetime(2024, 1, d), [100.0 + d, 101.0 + d, 100.5 + d])
    out = VolatilityAnalyzer(pl.DataFrame(rows)).yang_zhang_volatility()
    assert out.height == 1
    yz = out["yang_zhang_vol_annual"][0]
    assert yz is not None and yz > 0 and math.isfinite(yz)
    assert out["n"][0] == 6
