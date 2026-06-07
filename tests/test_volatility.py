"""Tests that the volatility estimators run on Polars 1.20 and isolate per symbol (R3)."""

import polars as pl

from energex.analysis.volatility import VolatilityAnalyzer


def test_realized_volatility_adds_column_for_all_symbols(sample_ohlcv):
    out = VolatilityAnalyzer(sample_ohlcv).calculate_realized_volatility(window_minutes=5)
    assert "realized_vol" in out.columns
    assert out.height == sample_ohlcv.height
    assert set(out["Symbol"].unique()) == {"CL=F", "NG=F"}


def test_parkinson_volatility_runs(sample_ohlcv):
    out = VolatilityAnalyzer(sample_ohlcv).calculate_parkinson_volatility(window_minutes=5)
    assert "parkinson_vol" in out.columns
    assert out.height == sample_ohlcv.height


def test_garman_klass_volatility_runs(sample_ohlcv):
    out = VolatilityAnalyzer(sample_ohlcv).calculate_garman_klass_volatility(window_minutes=5)
    assert "garman_klass_vol" in out.columns


def test_volatility_metrics_combines_all_measures(sample_ohlcv):
    out = VolatilityAnalyzer(sample_ohlcv).calculate_volatility_metrics()
    for col in (
        "realized_vol",
        "parkinson_vol",
        "garman_klass_vol",
        "vol_ratio_pk_rv",
        "vol_ratio_gk_rv",
        "intraday_range_pct",
    ):
        assert col in out.columns


def test_rolling_window_resets_per_symbol(sample_ohlcv):
    # With .over('Symbol') the rolling window must restart for each symbol, so the
    # first NG=F row cannot inherit CL=F's tail.
    out = (
        VolatilityAnalyzer(sample_ohlcv)
        .calculate_realized_volatility(window_minutes=10)
        .sort(["Symbol", "Datetime"])
    )
    ng_first = out.filter(pl.col("Symbol") == "NG=F").sort("Datetime")["realized_vol"][0]
    assert ng_first is None
