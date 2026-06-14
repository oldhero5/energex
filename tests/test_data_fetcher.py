"""Tests for ingestion resilience: retries, error classification, logging (R10)."""

import logging
from datetime import date

import pandas as pd
import polars as pl
import pytest

from energex import data_fetcher as df_mod
from energex.data_fetcher import MONTH_CODES, EnergyDataFetcher, _dated_tickers
from energex.exceptions import DataFetchError


def test_dated_tickers_count_codes_and_months():
    out = _dated_tickers("CL", date(2024, 1, 15), 12)
    assert len(out) == 12
    # First contract: January code 'F', year 24, first of month.
    assert out[0] == ("CLF24.NYM", date(2024, 1, 1))
    # Codes follow F G H J K M N Q U V X Z over the year.
    assert [t[0][2] for t in out] == list(MONTH_CODES)
    assert [t[1] for t in out] == [date(2024, m, 1) for m in range(1, 13)]


def test_dated_tickers_year_rollover():
    out = _dated_tickers("NG", date(2024, 11, 1), 3)
    assert out[0] == ("NGX24.NYM", date(2024, 11, 1))
    assert out[1] == ("NGZ24.NYM", date(2024, 12, 1))
    # Rolls into the next year with the January code.
    assert out[2] == ("NGF25.NYM", date(2025, 1, 1))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Keep retry/backoff tests fast.
    monkeypatch.setattr(df_mod.time, "sleep", lambda *_a, **_k: None)


def _fetcher(retries: int = 3) -> EnergyDataFetcher:
    f = EnergyDataFetcher()
    f.retries = retries
    f.timeout = 5
    return f


def test_raises_datafetcherror_after_exhausting_retries(monkeypatch):
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("network down")

    monkeypatch.setattr(df_mod.yf, "download", boom)
    with pytest.raises(DataFetchError):
        _fetcher(retries=3).get_commodity_data("crude")
    assert calls["n"] == 3  # all attempts used


def test_empty_result_returns_empty_frame_without_raising(monkeypatch):
    monkeypatch.setattr(df_mod.yf, "download", lambda *_a, **_k: pd.DataFrame())
    out = _fetcher().get_commodity_data("crude")
    assert isinstance(out, pl.DataFrame)
    assert out.is_empty()


def test_retries_then_succeeds(monkeypatch):
    state = {"n": 0}
    pdf = pd.DataFrame(
        {"Open": [75.0], "High": [76.0], "Low": [74.0], "Close": [75.5], "Volume": [1000]},
        index=pd.DatetimeIndex(["2024-01-02 14:30"], name="Datetime"),
    )

    def flaky(*_a, **_k):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient")
        return pdf

    monkeypatch.setattr(df_mod.yf, "download", flaky)
    out = _fetcher(retries=3).get_commodity_data("crude")
    assert state["n"] == 2
    assert out.height == 1
    assert out["Symbol"][0] == "CL=F"


def test_fetch_all_skips_failed_symbols(monkeypatch):
    fetcher = _fetcher()

    def fake_get(commodity: str) -> pl.DataFrame:
        if commodity == "brent":
            raise DataFetchError("boom")
        ticker = fetcher.ENERGY_SYMBOLS[commodity]["ticker"]
        return pl.DataFrame(
            {
                "Datetime": [pd.Timestamp("2024-01-02 14:30").to_pydatetime()],
                "Symbol": [ticker],
                "Open": [1.0],
                "High": [1.0],
                "Low": [1.0],
                "Close": [1.0],
                "Volume": [1],
            }
        )

    monkeypatch.setattr(fetcher, "get_commodity_data", fake_get)
    out = fetcher.fetch_all_commodities()
    assert not out.is_empty()
    assert "BZ=F" not in out["Symbol"].to_list()
    assert "CL=F" in out["Symbol"].to_list()


def test_logs_warning_on_empty_result(monkeypatch, caplog):
    monkeypatch.setattr(df_mod.yf, "download", lambda *_a, **_k: pd.DataFrame())
    with caplog.at_level(logging.WARNING, logger="energex.data_fetcher"):
        _fetcher().get_commodity_data("crude")
    assert any("No data" in r.message for r in caplog.records)
