# src/energex/data_fetcher.py
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import polars as pl
import yfinance as yf

from energex.config import get_settings
from energex.database import EnergyDatabase
from energex.exceptions import DataFetchError

logger = logging.getLogger(__name__)

#: CME/NYMEX delivery-month codes, January..December.
MONTH_CODES = "FGHJKMNQUVXZ"


def _dated_tickers(root: str, start: date, count: int) -> list[tuple[str, date]]:
    """Enumerate the next ``count`` monthly contracts from ``start``'s month.

    Returns ``(ticker, contract_month)`` pairs where ``ticker`` is the NYMEX symbol
    (e.g. ``CLZ26.NYM``) and ``contract_month`` is the first day of the delivery month.
    Pure and network-free for unit testing.
    """
    out: list[tuple[str, date]] = []
    year, month = start.year, start.month
    for _ in range(count):
        contract_month = date(year, month, 1)
        ticker = f"{root}{MONTH_CODES[month - 1]}{year % 100:02d}.NYM"
        out.append((ticker, contract_month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


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
        self.end_time = datetime.now(timezone.utc)
        self.start_time = self.end_time - timedelta(days=1)
        self.dated_lookback_days = settings.data_fetch.dated_lookback_days
        self.dated_contract_count = settings.data_fetch.dated_contract_count

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

    def _download_daily_with_retry(self, ticker: str, period_days: int) -> Any:
        """Download daily bars for a dated contract with timeout and backoff.

        Mirrors ``_download_with_retry`` but uses a daily interval over a recent window.
        """
        period = f"{period_days}d"
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                return yf.download(
                    ticker,
                    period=period,
                    interval="1d",
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

    def fetch_dated_contracts(self, commodity: str) -> pl.DataFrame:
        """Fetch the dated forward contract strip for one commodity.

        Enumerates the next ``dated_contract_count`` monthly NYMEX contracts from the
        commodity root (CL/BZ/NG) and fetches each contract's recent daily bars. A
        single contract returning empty (transient yfinance miss) is logged and skipped;
        it never raises. Returns a frame with ``DAILY_CONTRACTS_COLUMNS``.
        """
        root = self.ENERGY_SYMBOLS[commodity]["ticker"].removesuffix("=F")
        today = datetime.now(timezone.utc).date()
        dfs: list[pl.DataFrame] = []
        for ticker, contract_month in _dated_tickers(root, today, self.dated_contract_count):
            try:
                data = self._download_daily_with_retry(ticker, self.dated_lookback_days)
            except DataFetchError as e:
                logger.warning("Skipping contract %s: %s", ticker, e)
                continue
            if data.empty:
                logger.info("No data for contract %s (%s)", ticker, commodity)
                continue

            pdf = data.reset_index()
            pdf.columns = [col[0] if isinstance(col, tuple) else col for col in pdf.columns]
            df = pl.from_pandas(pdf).rename({"Date": "Datetime"})
            if "OpenInterest" not in df.columns:
                df = df.with_columns(pl.lit(None, dtype=pl.Int64).alias("OpenInterest"))
            df = df.with_columns(
                pl.lit(commodity).alias("Commodity"),
                pl.lit(contract_month).alias("ContractMonth"),
                pl.lit(ticker).alias("Symbol"),
                pl.col("OpenInterest").cast(pl.Int64),
            )
            # Daily bars come back tz-naive (date-only); stamp them as UTC
            # explicitly so the TIMESTAMPTZ column is host-independent rather
            # than relying on the session TimeZone at insert time.
            dt = df.schema["Datetime"]
            if isinstance(dt, pl.Datetime) and dt.time_zone is None:
                df = df.with_columns(pl.col("Datetime").dt.replace_time_zone("UTC"))
            df = normalize_datetime_to_utc(df)
            df = df.select(EnergyDatabase.DAILY_CONTRACTS_COLUMNS)
            dfs.append(df)

        if not dfs:
            logger.warning("No dated contracts fetched for %s", commodity)
            return pl.DataFrame()
        return pl.concat(dfs)

    def fetch_all_dated(self) -> pl.DataFrame:
        """Fetch and concatenate the dated contract strip for all commodities."""
        dfs = [
            df
            for commodity in self.ENERGY_SYMBOLS
            if not (df := self.fetch_dated_contracts(commodity)).is_empty()
        ]
        if not dfs:
            return pl.DataFrame()
        return pl.concat(dfs)

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
