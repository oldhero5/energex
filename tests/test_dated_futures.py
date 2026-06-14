"""Tests for DatedFuturesAnalyzer term-structure analytics."""

from datetime import date

from energex.analysis.dated_futures import DatedFuturesAnalyzer

ASOF = date(2024, 1, 2)


def test_curve_as_of_sorted_with_days_to_maturity(sample_daily_contracts):
    curve = DatedFuturesAnalyzer(sample_daily_contracts).curve_as_of("crude", ASOF)
    assert curve.height == 6
    months = curve["ContractMonth"].to_list()
    assert months == sorted(months)
    # First contract month is 2024-02-01 -> 30 days out from 2024-01-02.
    assert curve["days_to_maturity"][0] == (date(2024, 2, 1) - ASOF).days


def test_backwardation_case(sample_daily_contracts):
    analyzer = DatedFuturesAnalyzer(sample_daily_contracts)
    slope = analyzer.term_structure_slope("crude", ASOF)
    assert slope < 0
    assert analyzer.shape("crude", ASOF) == "backwardation"


def test_contango_case(sample_daily_contracts):
    analyzer = DatedFuturesAnalyzer(sample_daily_contracts)
    slope = analyzer.term_structure_slope("gas", ASOF)
    assert slope > 0
    assert analyzer.shape("gas", ASOF) == "contango"


def test_roll_yield_signs(sample_daily_contracts):
    analyzer = DatedFuturesAnalyzer(sample_daily_contracts)
    crude = analyzer.roll_yield("crude", ASOF)
    assert crude.height == 5
    # Backwardation: near > far -> positive roll yield.
    assert all(v > 0 for v in crude["roll_yield"].to_list())

    gas = analyzer.roll_yield("gas", ASOF)
    assert all(v < 0 for v in gas["roll_yield"].to_list())


def test_slope_nan_safe_when_single_contract(sample_daily_contracts):
    one = sample_daily_contracts.filter(sample_daily_contracts["ContractMonth"] == date(2024, 2, 1))
    slope = DatedFuturesAnalyzer(one).term_structure_slope("crude", ASOF)
    assert slope != slope  # nan
    assert DatedFuturesAnalyzer(one).shape("crude", ASOF) == "flat"
