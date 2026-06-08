"""yfinance data source — PERSONAL RESEARCH ONLY.

Yahoo's terms prohibit automated/commercial use; 1-minute history is capped at ~7 days
per request; CL=F/BZ=F/NG=F are continuous front-month *proxies*, not dated contracts.
Use a licensed source (see energex.sources.stubs) for production / curve analytics.
"""

import polars as pl

from energex.data_fetcher import EnergyDataFetcher
from energex.sources.base import DataSource


class YFinanceDataSource(DataSource):
    name = "yfinance"
    redistributable = False

    def __init__(self) -> None:
        self._fetcher = EnergyDataFetcher()

    def fetch(self, commodity: str) -> pl.DataFrame:
        return self._fetcher.get_commodity_data(commodity)

    def fetch_all(self) -> pl.DataFrame:
        return self._fetcher.fetch_all_commodities()
