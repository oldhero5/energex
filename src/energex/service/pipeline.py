"""Ingestion pipeline: fetch (via a pluggable DataSource) -> upsert -> checkpoint."""

import logging
import os

from energex.database import EnergyDatabase
from energex.sources import get_data_source

logger = logging.getLogger(__name__)


def run_ingestion(db: EnergyDatabase, source_name: str | None = None) -> int:
    """Fetch all commodities and upsert into the store.

    The data source defaults to ENERGEX_DATA_SOURCE (or 'yfinance'). Safe to run
    repeatedly: the upsert merges overlapping windows, so a missed or duplicated run
    is idempotent.
    """
    source = get_data_source(source_name or os.environ.get("ENERGEX_DATA_SOURCE", "yfinance"))
    df = source.fetch_all()
    if df.is_empty():
        logger.info("Ingestion produced no rows (source=%s)", source.name)
        return 0
    db.insert_intraday_data(df)
    db.conn.execute("CHECKPOINT")
    logger.info("Ingestion upserted %d rows (source=%s)", df.height, source.name)
    return df.height
