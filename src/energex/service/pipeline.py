"""Ingestion pipeline: fetch -> idempotent upsert -> checkpoint."""

import logging

from energex.data_fetcher import EnergyDataFetcher
from energex.database import EnergyDatabase

logger = logging.getLogger(__name__)


def run_ingestion(db: EnergyDatabase) -> int:
    """Fetch all commodities and upsert into the store.

    Returns the number of rows upserted. Safe to run repeatedly: the upsert merges
    overlapping windows, so a missed or duplicated run is idempotent.
    """
    fetcher = EnergyDataFetcher()
    df = fetcher.fetch_all_commodities()
    if df.is_empty():
        logger.info("Ingestion produced no rows")
        return 0
    db.insert_intraday_data(df)
    db.conn.execute("CHECKPOINT")
    logger.info("Ingestion upserted %d rows", df.height)
    return df.height
