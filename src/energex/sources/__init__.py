"""Pluggable market-data sources.

>>> from energex.sources import get_data_source
>>> source = get_data_source("yfinance")  # default
>>> df = source.fetch_all()
"""

from energex.exceptions import ConfigurationError
from energex.sources.base import DataSource
from energex.sources.stubs import (
    DatabentoDataSource,
    EIASpotDataSource,
    ICEBrentDataSource,
)
from energex.sources.yfinance_source import YFinanceDataSource

_SOURCES: dict[str, type[DataSource]] = {
    "yfinance": YFinanceDataSource,
    "databento": DatabentoDataSource,
    "ice-brent": ICEBrentDataSource,
    "eia-spot": EIASpotDataSource,
}


def get_data_source(name: str = "yfinance") -> DataSource:
    """Construct a data source by name (default: yfinance)."""
    key = name.lower()
    if key not in _SOURCES:
        raise ConfigurationError(f"Unknown data source: {name}. Available: {sorted(_SOURCES)}")
    return _SOURCES[key]()


def list_data_sources() -> list[str]:
    return sorted(_SOURCES)


__all__ = [
    "DataSource",
    "YFinanceDataSource",
    "DatabentoDataSource",
    "ICEBrentDataSource",
    "EIASpotDataSource",
    "get_data_source",
    "list_data_sources",
]
