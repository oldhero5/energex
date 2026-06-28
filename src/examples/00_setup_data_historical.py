# examples/00_setup_data_historical.py
"""
Setup script using historical data for testing when markets are closed.

Use this version when:
- Markets are closed (weekends, holidays, after hours)
- You need sample data for testing examples
- Christmas Day, New Year's, or other market holidays

This fetches the most recent available historical data instead of
real-time intraday data.

Usage:
    python src/examples/00_setup_data_historical.py
"""


import polars as pl
import yfinance as yf

from energex import EnergyDatabase

print("=" * 70)
print("ENERGEX - Historical Data Setup for Examples")
print("=" * 70)
print("\nℹ️  This script fetches recent DAILY data (not intraday)")
print("   Use this when markets are closed for testing purposes.")

# Initialize database
print("\n[1/3] Initializing database...")
db = EnergyDatabase()
print(f"✅ Database: {db.db_path}")

# Fetch historical daily data
print("\n[2/3] Fetching historical daily data...")
print("This will fetch the last 30 days of daily OHLCV data")

symbols = ['CL=F', 'BZ=F', 'NG=F']
names = {
    'CL=F': 'WTI Crude Oil',
    'BZ=F': 'Brent Crude',
    'NG=F': 'Natural Gas'
}

all_data = []

for symbol in symbols:
    try:
        print(f"\nFetching {names[symbol]} ({symbol})...")

        # Fetch last 30 days of daily data
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d", interval="1d")

        if hist.empty:
            print(f"  ⚠️  No data available for {symbol}")
            continue

        # Reset index and prepare DataFrame
        hist = hist.reset_index()

        # Convert to Polars DataFrame
        df = pl.DataFrame({
            'Datetime': hist['Date'].dt.tz_localize('UTC').tolist(),
            'Symbol': [symbol] * len(hist),
            'Open': hist['Open'].tolist(),
            'High': hist['High'].tolist(),
            'Low': hist['Low'].tolist(),
            'Close': hist['Close'].tolist(),
            'Volume': hist['Volume'].astype('int64').tolist()
        })

        all_data.append(df)
        print(f"  ✅ Got {len(df)} days of data")
        print(f"     Date range: {df['Datetime'].min()} to {df['Datetime'].max()}")

    except Exception as e:
        print(f"  ❌ Error fetching {symbol}: {e}")
        continue

if not all_data:
    print("\n❌ No data could be fetched!")
    print("\nPossible reasons:")
    print("  - No internet connection")
    print("  - Yahoo Finance API issues")
    print("  - All symbols are temporarily unavailable")
    exit(1)

# Combine all data
print("\n[3/3] Storing data in database...")
combined_data = pl.concat(all_data).sort(['Symbol', 'Datetime'])

# Insert into database
db.insert_intraday_data(combined_data)
print("✅ Data storage complete!")

# Verify data
query = "SELECT Symbol, COUNT(*) as count, MIN(Datetime) as first, MAX(Datetime) as last FROM intraday_prices GROUP BY Symbol"
result = pl.from_arrow(db.conn.execute(query).arrow())

print("\nData Summary:")
print(result)

print("\n" + "=" * 70)
print("✅ Setup complete! You can now run the example scripts.")
print("=" * 70)
print("\nℹ️  Note: Examples will use DAILY data (not 1-minute intraday)")
print("   This is perfect for testing, but results will differ from")
print("   production usage with real-time intraday data.")
print("\nNext steps:")
print("  python src/examples/01_data_quality_analysis.py")
print("  python src/examples/02_volatility_analysis.py")
print("  python src/examples/03_futures_analysis.py")
print("  python src/examples/04_sentiment_analysis.py")
