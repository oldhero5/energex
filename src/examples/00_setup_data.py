# examples/00_setup_data.py
"""
Setup script to fetch initial data for running examples.

Run this first before running any other examples:
    python src/examples/00_setup_data.py

This will populate the database with recent market data.
"""

import polars as pl
from energex import EnergyDatabase, EnergyDataFetcher

print("=" * 70)
print("ENERGEX - Data Setup for Examples")
print("=" * 70)

# Initialize database
print("\n[1/3] Initializing database...")
db = EnergyDatabase()
print(f"✅ Database: {db.db_path}")

# Initialize fetcher
print("\n[2/3] Initializing data fetcher...")
fetcher = EnergyDataFetcher()
print("✅ Data fetcher ready")

# Fetch data for all energy symbols
print("\n[3/3] Fetching market data...")
print("This will take 2-3 minutes. Fetching:")
print("  - CL=F (WTI Crude Oil)")
print("  - BZ=F (Brent Crude)")
print("  - NG=F (Natural Gas)")

try:
    # Fetch all commodity data
    data = fetcher.fetch_all_commodities()

    if data.is_empty():
        print("\n❌ No data fetched!")
        print("This can happen during market hours or weekends.")
        print("Try running during US market hours (9:30 AM - 4:00 PM ET).")
        exit(1)

    # Insert into database
    db.insert_intraday_data(data)
    print("\n✅ Data fetch and storage complete!")

    # Verify data
    query = "SELECT Symbol, COUNT(*) as count, MIN(Datetime) as first, MAX(Datetime) as last FROM intraday_prices GROUP BY Symbol"
    result = pl.from_arrow(db.conn.execute(query).arrow())

    print("\nData Summary:")
    print(result)

    print("\n" + "=" * 70)
    print("✅ Setup complete! You can now run the example scripts.")
    print("=" * 70)
    print("\nNext steps:")
    print("  python src/examples/01_data_quality_analysis.py")
    print("  python src/examples/02_volatility_analysis.py")
    print("  python src/examples/03_futures_analysis.py")
    print("  python src/examples/04_sentiment_analysis.py")

except Exception as e:
    print(f"\n❌ Error fetching data: {e}")
    print("\nTroubleshooting:")
    print("  - Check your internet connection")
    print("  - Verify yfinance is installed: pip install yfinance")
    print("  - Try running during market hours")
    print("  - Markets may be closed (weekends/holidays)")
