# src/energex/main.py
import argparse
from datetime import datetime

from energex.data_fetcher import EnergyDataFetcher
from energex.database import EnergyDatabase


def update_intraday_data(db_path: str = "energy.db") -> None:
    """Update intraday data for all commodities (idempotent upsert into the store)."""
    db = EnergyDatabase(db_path)
    fetcher = EnergyDataFetcher()

    print(f"\nStarting intraday data update at {datetime.now()}")

    successful = []
    failed = []

    for symbol in fetcher.ENERGY_SYMBOLS:
        try:
            print(f"\nProcessing {symbol}...")
            df = fetcher.get_commodity_data(symbol)

            if not df.is_empty():
                db.insert_intraday_data(df)
                successful.append(symbol)
            else:
                failed.append((symbol, "No data returned"))

        except Exception as e:
            print(f"Error processing {symbol}: {str(e)}")
            failed.append((symbol, str(e)))

    # Print summary
    print("\nUpdate Summary:")
    print(f"Successfully processed: {len(successful)} symbols")
    if successful:
        print("Successful symbols:", ", ".join(successful))
    if failed:
        print("\nFailed symbols:")
        for symbol, error in failed:
            print(f"- {symbol}: {error}")


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
        print(f"Reset database at {db_path}")
    finally:
        db.conn.close()


def main() -> None:
    """Main entry point."""
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
            print(row)
    elif args.reset:
        reset_database()
    else:
        update_intraday_data()


if __name__ == "__main__":
    main()
