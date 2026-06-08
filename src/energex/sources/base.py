"""Abstract market-data source.

A DataSource returns standardized OHLCV frames (UTC instants, the canonical column
set) so the rest of energex is decoupled from any single vendor. yfinance becomes one
opt-in adapter among licensed alternatives (ASSESSMENT R14).
"""

from abc import ABC, abstractmethod

import polars as pl


class DataSource(ABC):
    """Base class for market-data sources."""

    #: Short identifier (e.g. "yfinance", "databento").
    name: str = "abstract"
    #: Whether the vendor's terms permit redistribution/commercial use.
    redistributable: bool = False

    @abstractmethod
    def fetch(self, commodity: str) -> pl.DataFrame:
        """Fetch one commodity key (e.g. 'crude', 'brent', 'gas')."""

    @abstractmethod
    def fetch_all(self) -> pl.DataFrame:
        """Fetch and combine all supported commodities."""
