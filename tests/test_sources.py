"""Tests for the pluggable data-source layer (R14)."""

import polars as pl
import pytest

from energex import data_fetcher as df_mod
from energex.exceptions import ConfigurationError
from energex.sources import get_data_source, list_data_sources
from energex.sources.yfinance_source import YFinanceDataSource


def test_default_source_is_yfinance_and_not_redistributable():
    src = get_data_source()
    assert isinstance(src, YFinanceDataSource)
    assert src.name == "yfinance"
    assert src.redistributable is False


def test_unknown_source_raises():
    with pytest.raises(ConfigurationError):
        get_data_source("nope")


def test_list_sources():
    assert set(list_data_sources()) == {"yfinance", "databento", "ice-brent", "eia-spot"}


def test_yfinance_source_delegates_to_fetcher(monkeypatch):
    fake = pl.DataFrame({"Symbol": ["CL=F"]})
    monkeypatch.setattr(df_mod.EnergyDataFetcher, "fetch_all_commodities", lambda self: fake)
    out = get_data_source("yfinance").fetch_all()
    assert out.equals(fake)


def test_yfinance_source_fetch_dated_delegates(monkeypatch):
    fake = pl.DataFrame({"Commodity": ["crude"]})
    monkeypatch.setattr(df_mod.EnergyDataFetcher, "fetch_all_dated", lambda self: fake)
    out = get_data_source("yfinance").fetch_dated()
    assert out.equals(fake)


@pytest.mark.parametrize("name", ["databento", "ice-brent", "eia-spot"])
def test_stub_sources_raise_not_implemented(name):
    src = get_data_source(name)
    assert src.redistributable is True
    with pytest.raises(NotImplementedError):
        src.fetch_all()
    with pytest.raises(NotImplementedError):
        src.fetch("crude")
    with pytest.raises(NotImplementedError):
        src.fetch_dated()
