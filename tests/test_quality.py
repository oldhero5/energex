"""Tests that data-quality checks run on Polars 1.20 and return correct types (R3)."""

from datetime import datetime

import polars as pl

from energex.analysis.quality import DataQualityChecker


def test_check_tick_quality_returns_scalar_counts(sample_ohlcv):
    metrics = DataQualityChecker(sample_ohlcv).check_tick_quality()
    assert isinstance(metrics["invalid_prices"], int)
    assert isinstance(metrics["invalid_ohlc"], int)
    assert isinstance(metrics["total_records"], int)
    assert metrics["total_records"] == sample_ohlcv.height
    # The sample frame is clean.
    assert metrics["invalid_prices"] == 0
    assert metrics["invalid_ohlc"] == 0


def test_check_tick_quality_detects_ohlc_inconsistency():
    df = pl.DataFrame(
        {
            "Datetime": [datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 1, 0, 1)],
            "Symbol": ["CL=F", "CL=F"],
            "Open": [10.0, 10.0],
            "High": [11.0, 9.0],  # second row: High < Low -> inconsistent
            "Low": [9.0, 10.0],
            "Close": [10.5, 9.5],
            "Volume": [1, 1],
        }
    )
    metrics = DataQualityChecker(df).check_tick_quality()
    assert metrics["invalid_ohlc"] == 1


def test_check_price_gaps_returns_dataframe(sample_ohlcv):
    out = DataQualityChecker(sample_ohlcv).check_price_gaps(threshold_pct=0.5)
    assert isinstance(out, pl.DataFrame)


def test_check_price_gaps_threshold_is_percent():
    # A +2% jump must be flagged at threshold_pct=1.0 but not at threshold_pct=5.0.
    df = pl.DataFrame(
        {
            "Datetime": [datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 1, 0, 1)],
            "Symbol": ["CL=F", "CL=F"],
            "Open": [100.0, 102.0],
            "High": [100.0, 102.0],
            "Low": [100.0, 102.0],
            "Close": [100.0, 102.0],  # +2%
            "Volume": [1, 1],
        }
    )
    flagged_at_1 = DataQualityChecker(df).check_price_gaps(threshold_pct=1.0)
    flagged_at_5 = DataQualityChecker(df).check_price_gaps(threshold_pct=5.0)
    assert flagged_at_1.height == 1
    assert flagged_at_5.height == 0


def test_check_volume_anomalies_returns_dataframe(sample_ohlcv):
    out = DataQualityChecker(sample_ohlcv).check_volume_anomalies()
    assert isinstance(out, pl.DataFrame)


def test_check_price_reversals_returns_dataframe(sample_ohlcv):
    out = DataQualityChecker(sample_ohlcv).check_price_reversals()
    assert isinstance(out, pl.DataFrame)
