# src/energex/main.py
import argparse
import logging
from datetime import datetime

from energex.config import get_settings
from energex.data_fetcher import EnergyDataFetcher
from energex.database import EnergyDatabase
from energex.logging_config import setup_logging

logger = logging.getLogger(__name__)


def update_intraday_data(db_path: str = "energy.db") -> None:
    """Update intraday data for all commodities (idempotent upsert into the store)."""
    db = EnergyDatabase(db_path)
    fetcher = EnergyDataFetcher()

    logger.info("Starting intraday data update at %s", datetime.now())

    successful: list[str] = []
    failed: list[tuple[str, str]] = []

    for symbol in fetcher.ENERGY_SYMBOLS:
        try:
            logger.info("Processing %s", symbol)
            df = fetcher.get_commodity_data(symbol)
            if not df.is_empty():
                db.insert_intraday_data(df)
                successful.append(symbol)
            else:
                failed.append((symbol, "No data returned"))
        except Exception as e:
            logger.error("Error processing %s: %s", symbol, e)
            failed.append((symbol, str(e)))

    logger.info("Update complete: %d succeeded, %d failed", len(successful), len(failed))
    if successful:
        logger.info("Successful symbols: %s", ", ".join(successful))
    for symbol, error in failed:
        logger.warning("Failed symbol %s: %s", symbol, error)


def check_schema(db_path: str = "energy.db") -> list[tuple[object, ...]]:
    """Return the intraday_prices schema using a READ-ONLY connection.

    Inspection must never mutate the store (the previous ``--check`` path dropped
    the table on connect).
    """
    db = EnergyDatabase(db_path, read_only=True)
    try:
        return db.conn.execute("DESCRIBE intraday_prices").fetchall()
    finally:
        db.conn.close()


def reset_database(db_path: str = "energy.db") -> None:
    """Drop and recreate the table. Destructive — explicit opt-in only."""
    db = EnergyDatabase(db_path)
    try:
        db.reset()
        logger.info("Reset database at %s", db_path)
    finally:
        db.conn.close()


def main() -> None:
    """Main entry point."""
    settings = get_settings()
    setup_logging(
        log_level=settings.logging.log_level,
        log_file=settings.logging.log_file,
        enable_console=settings.logging.log_enable_console,
    )

    parser = argparse.ArgumentParser(description="Energy commodity data collector")
    parser.add_argument(
        "--check", action="store_true", help="Inspect the database schema (read-only)"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate the table (DESTRUCTIVE; deletes all history)",
    )

    args = parser.parse_args()

    if args.check:
        for row in check_schema():
            logger.info("%s", row)
    elif args.reset:
        reset_database()
    else:
        update_intraday_data()


if __name__ == "__main__":
    main()
