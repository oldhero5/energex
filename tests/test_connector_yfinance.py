"""Offline, deterministic unit test for the yfinance intraday connector.

yfinance does not use httpx, so respx cannot intercept it; instead the network seam
(``yf.download``) is monkeypatched to return a captured-shape sample frame. No live
network is touched. The shaped FetchResult must satisfy the SAME core.quality OHLCV
gate the Dagster asset runs.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from energex.core import quality, schemas
from energex.core.connectors import Connector
from energex.core.connectors import yfinance as yfconn
from energex.core.connectors.yfinance import YFinanceIntradayConnector


def _sample(ticker: str, *, n: int = 5, base: float = 75.0) -> pd.DataFrame:
    """A yfinance-shaped 1m frame: (Field, Ticker) MultiIndex cols, tz-aware index.

    Timestamps end ~now so the freshness wide-check passes against fetched_at.
    """
    end = pd.Timestamp.now(tz="America/New_York").floor("min")
    idx = pd.date_range(end=end, periods=n, freq="min", tz="America/New_York")
    idx.name = "Datetime"
    data = {
        ("Open", ticker): [base + j * 0.01 for j in range(n)],
        ("High", ticker): [base + 0.2 + j * 0.01 for j in range(n)],
        ("Low", ticker): [base - 0.2 + j * 0.01 for j in range(n)],
        ("Close", ticker): [base + 0.05 + j * 0.01 for j in range(n)],
        ("Volume", ticker): [1000 + j * 10 for j in range(n)],
    }
    return pd.DataFrame(data, index=idx, columns=pd.MultiIndex.from_tuples(list(data)))


def test_fetch_shapes_frontmonth_bars_passing_the_gate(monkeypatch):
    monkeypatch.setattr(yfconn.yf, "download", lambda ticker, **_: _sample(ticker))

    conn = YFinanceIntradayConnector()
    assert isinstance(conn, Connector)  # satisfies the contract Protocol

    result = conn.fetch(date(2026, 6, 15), date(2026, 6, 16))

    assert result.source == "yfinance"
    assert result.fetched_at.tzinfo is not None  # tz-aware UTC knowledge time
    assert result.complete_over_range is False

    frame = result.frame
    assert list(frame.columns) == [
        "instrument_id",
        "valid_time",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]
    assert set(frame["instrument_id"]) == {"CME.CL.FRONT", "CME.BZ.FRONT", "CME.NG.FRONT"}
    assert str(frame["valid_time"].dtype) == "datetime64[ns, UTC]"
    assert frame["Volume"].dtype == "int64"
    assert len(frame) == 15  # 3 tickers x 5 bars

    # The frame must pass the exact OHLCV gate the asset runs (single-sourced).
    validated = quality.validate(frame, schemas.OHLCV, as_of=result.fetched_at)
    assert len(validated) == 15


def test_fetch_skips_empty_tickers(monkeypatch):
    def fake_download(ticker, **_):
        return _sample(ticker) if ticker == "CL=F" else pd.DataFrame()

    monkeypatch.setattr(yfconn.yf, "download", fake_download)

    result = YFinanceIntradayConnector().fetch(date(2026, 6, 15), date(2026, 6, 16))
    assert set(result.frame["instrument_id"]) == {"CME.CL.FRONT"}
    assert len(result.frame) == 5


def test_fetch_retries_transient_failure(monkeypatch):
    calls: dict[str, int] = dict.fromkeys(yfconn.TICKERS, 0)

    def fake_download(ticker, **_):
        calls[ticker] += 1
        if ticker == "CL=F" and calls[ticker] == 1:
            raise RuntimeError("transient 503")
        return _sample(ticker)

    monkeypatch.setattr(yfconn.yf, "download", fake_download)

    result = YFinanceIntradayConnector(retries=3, timeout=5).fetch(
        date(2026, 6, 15), date(2026, 6, 16)
    )
    assert calls["CL=F"] == 2  # one retry then success
    assert len(result.frame) == 15


def test_fetch_all_empty_returns_typed_empty_frame(monkeypatch):
    monkeypatch.setattr(yfconn.yf, "download", lambda ticker, **_: pd.DataFrame())

    result = YFinanceIntradayConnector().fetch(date(2026, 6, 15), date(2026, 6, 16))
    assert result.frame.empty
    assert list(result.frame.columns) == [
        "instrument_id",
        "valid_time",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]
    assert isinstance(result.fetched_at, datetime)
