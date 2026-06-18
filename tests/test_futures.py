"""Tests for FuturesAnalyzer: working spreads + gated expiry-dependent methods (R4)."""

import pytest

from energex.analysis.futures import FuturesAnalyzer


def test_term_structure_computes_cross_symbol_spread(sample_ohlcv):
    out = FuturesAnalyzer(sample_ohlcv).calculate_term_structure("CL=F", "NG=F")
    assert "spread" in out.columns
    assert out.height > 0


def test_basis_risk_computes_spread(sample_ohlcv):
    out = FuturesAnalyzer(sample_ohlcv).calculate_basis_risk("CL=F", "NG=F")
    assert "basis" in out.columns
    assert out.height > 0


@pytest.mark.parametrize(
    "call",
    [
        lambda a: a.analyze_roll_yield("CL=F", "NG=F"),
        lambda a: a.analyze_futures_curve(["CL=F", "NG=F"]),
        lambda a: a.calculate_implied_rates("CL=F", "NG=F", 0.05),
    ],
)
def test_expiry_dependent_methods_raise_not_implemented(sample_ohlcv, call):
    # These require a contract-month/expiry data model that does not exist yet;
    # they must fail clearly rather than crash deep in Polars on a missing column.
    with pytest.raises(NotImplementedError):
        call(FuturesAnalyzer(sample_ohlcv))
