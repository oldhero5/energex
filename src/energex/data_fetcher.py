# src/energex/data_fetcher.py
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import polars as pl
import pytz
import yfinance as yf

from energex.config import get_settings
from energex.exceptions import DataFetchError

logger = logging.getLogger(__name__)


def normalize_datetime_to_utc(df: pl.DataFrame) -> pl.DataFrame:
    """Convert a tz-aware Datetime column to a UTC instant.

    yfinance returns exchange-tz-aware bars; storing them as a single UTC instant makes
    the (Symbol, Datetime) key host-independent. Naive or absent columns are returned
    unchanged (the storage layer interprets naive timestamps as UTC).
    """
    if df.is_empty() or "Datetime" not in df.columns:
        return df
    dtype = df.schema["Datetime"]
    if isinstance(dtype, pl.Datetime) and dtype.time_zone is not None:
        return df.with_columns(pl.col("Datetime").dt.convert_time_zone("UTC"))
    return df


class EnergyDataFetcher:
    ENERGY_SYMBOLS = {
        "crude": {"ticker": "CL=F", "name": "Crude Oil Futures"},
        "brent": {"ticker": "BZ=F", "name": "Brent Crude Oil Futures"},
        "gas": {"ticker": "NG=F", "name": "Natural Gas Futures"},
    }

    def __init__(self) -> None:
        settings = get_settings()
        self.timeout = settings.data_fetch.yfinance_timeout
        self.retries = max(1, settings.data_fetch.data_fetch_retries)
        self.end_time = datetime.now(pytz.UTC)
        self.start_time = self.end_time - timedelta(days=1)

    def _download_with_retry(self, ticker: str) -> Any:
        """Download with a timeout and exponential backoff; raise on real failure."""
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                return yf.download(
                    ticker,
                    start=self.start_time,
                    end=self.end_time,
                    interval="1m",
                    timeout=self.timeout,
                )
            except Exception as e:
                last_exc = e
                logger.warning(
                    "Download attempt %d/%d for %s failed: %s", attempt, self.retries, ticker, e
                )
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 10))
        raise DataFetchError(
            f"Failed to download {ticker} after {self.retries} attempts"
        ) from last_exc

    def get_commodity_data(self, commodity: str) -> pl.DataFrame:
        """Fetch intraday data for one commodity key (crude, brent, gas).

        Returns an empty DataFrame only for a genuinely empty result; a real download
        failure raises DataFetchError so callers can distinguish an outage from a
        quiet (weekend/holiday) market.
        """
        ticker = self.ENERGY_SYMBOLS[commodity]["ticker"]
        logger.info("Downloading %s (%s)", commodity, ticker)

        data = self._download_with_retry(ticker)
        if data.empty:
            logger.warning("No data returned for %s (%s)", commodity, ticker)
            return pl.DataFrame()

        # Reset index and flatten any multi-index columns.
        df = data.reset_index()
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

        df = pl.from_pandas(df).with_columns(pl.lit(ticker).alias("Symbol"))
        df = df.sort(["Symbol", "Datetime"]).select(
            ["Datetime", "Symbol", "Open", "High", "Low", "Close", "Volume"]
        )
        df = normalize_datetime_to_utc(df)

        logger.info("Got %d rows for %s (%s)", len(df), commodity, ticker)
        return df

    def fetch_all_commodities(self) -> pl.DataFrame:
        """Fetch and combine all commodities; a failed symbol is logged and skipped."""
        dfs = []
        for commodity in self.ENERGY_SYMBOLS:
            try:
                df = self.get_commodity_data(commodity)
                if not df.is_empty():
                    dfs.append(df)
            except DataFetchError as e:
                logger.error("Failed to fetch %s: %s", commodity, e)
                continue

        if not dfs:
            return pl.DataFrame()

        combined = pl.concat(dfs)
        return combined.sort(["Symbol", "Datetime"]).select(
            ["Datetime", "Symbol", "Open", "High", "Low", "Close", "Volume"]
        )
