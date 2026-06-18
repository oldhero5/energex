"""yfinance intraday connector: front-month futures 1m OHLCV -> FetchResult.

PERSONAL RESEARCH ONLY (Yahoo's terms prohibit automated/commercial use; 1-minute
history is capped at ~7 days/request). The three continuous front-month proxies
CL=F/BZ=F/NG=F are emitted as the degenerate intraday instrument_ids
CME.{CL,BZ,NG}.FRONT. Network calls go through tenacity retry with the configured
yfinance timeout; ``valid_time`` is tz-aware UTC.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from energex.core.config import get_settings
from energex.core.connectors.base import FetchResult

logger = logging.getLogger(__name__)

# yfinance continuous front-month proxy ticker -> degenerate intraday instrument_id.
TICKERS: dict[str, str] = {
    "CL=F": "CME.CL.FRONT",
    "BZ=F": "CME.BZ.FRONT",
    "NG=F": "CME.NG.FRONT",
}

#: instrument_ids this connector produces (consumed by the asset + asset_check).
INSTRUMENT_IDS: list[str] = list(TICKERS.values())

_VALUE_COLS = ["Open", "High", "Low", "Close", "Volume"]
_FRAME_COLS = ["instrument_id", "valid_time", *_VALUE_COLS]
_SOURCE = "yfinance"
_SOURCE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


def _empty_frame() -> pd.DataFrame:
    cols: dict[str, pd.Series] = {
        "instrument_id": pd.Series(dtype="object"),
        "valid_time": pd.Series(dtype="datetime64[ns, UTC]"),
        "Open": pd.Series(dtype="float64"),
        "High": pd.Series(dtype="float64"),
        "Low": pd.Series(dtype="float64"),
        "Close": pd.Series(dtype="float64"),
        "Volume": pd.Series(dtype="int64"),
    }
    return pd.DataFrame(cols)


def _shape(raw: pd.DataFrame, instrument_id: str) -> pd.DataFrame:
    """yfinance OHLCV frame -> canonical (instrument_id, tz-aware-UTC valid_time, OHLCV)."""
    if raw is None or raw.empty:
        return _empty_frame()
    df = raw.reset_index()
    # yfinance returns a (Field, Ticker) column MultiIndex; flatten to the field name.
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    time_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
    out = pd.DataFrame(
        {
            "instrument_id": instrument_id,
            # tz-aware exchange instants -> UTC; naive instants localized to UTC.
            "valid_time": pd.to_datetime(df[time_col], utc=True),
        }
    )
    for col in ["Open", "High", "Low", "Close"]:
        out[col] = pd.to_numeric(df[col]).astype("float64")
    out["Volume"] = pd.to_numeric(df["Volume"]).fillna(0).astype("int64")
    return out


class YFinanceIntradayConnector:
    """Connector for continuous front-month 1-minute OHLCV bars (degenerate)."""

    source = _SOURCE

    def __init__(self, *, timeout: int | None = None, retries: int | None = None) -> None:
        fetch_cfg = get_settings().data_fetch
        self._timeout = fetch_cfg.yfinance_timeout if timeout is None else timeout
        self._retries = max(1, fetch_cfg.data_fetch_retries if retries is None else retries)

    def fetch(self, window_start: date, window_end: date) -> FetchResult:
        fetched_at = datetime.now(timezone.utc)
        frames: list[pd.DataFrame] = []
        for ticker, instrument_id in TICKERS.items():
            raw = self._download(ticker, window_start, window_end)
            shaped = _shape(raw, instrument_id)
            if shaped.empty:
                logger.info(
                    "No 1m bars for %s (%s) in [%s, %s)",
                    instrument_id,
                    ticker,
                    window_start,
                    window_end,
                )
                continue
            frames.append(shaped)
        frame = pd.concat(frames, ignore_index=True) if frames else _empty_frame()
        return FetchResult(
            frame=frame[_FRAME_COLS],
            source=self.source,
            fetched_at=fetched_at,
            source_url=_SOURCE_URL,
            # A 1m slice is never the full as-known series for its span (degenerate).
            complete_over_range=False,
        )

    def _download(self, ticker: str, window_start: date, window_end: date) -> Any:
        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=1, max=10),
            reraise=True,
        )
        def _go() -> Any:
            return yf.download(
                ticker,
                start=window_start,
                end=window_end,
                interval="1m",
                timeout=self._timeout,
                progress=False,
                auto_adjust=False,
            )

        return _go()
