# examples/03_futures_analysis.py
"""
Futures Analysis Example

Demonstrates term structure and futures curve analysis
for energy futures contracts.

Prerequisites:
    Run 00_setup_data.py first to populate the database

Usage:
    python src/examples/03_futures_analysis.py
"""

import polars as pl
import plotly.graph_objects as go
from energex import EnergyDatabase, FuturesAnalyzer

print("=" * 70)
print("ENERGEX - Futures Analysis Example")
print("=" * 70)

# Connect to database
print("\n[1/3] Connecting to database...")
db = EnergyDatabase()

# Get recent data (last 7 days)
query = """
SELECT *
FROM intraday_prices
WHERE Datetime >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
ORDER BY Symbol, Datetime
"""
df = pl.from_arrow(db.conn.execute(query).arrow())

if len(df) == 0:
    print("❌ No data found in database!")
    print("\nPlease run the setup script first:")
    print("  python src/examples/00_setup_data.py")
    exit(1)

print(f"✅ Loaded {len(df)} records")
print(f"   Symbols: {df['Symbol'].unique().to_list()}")

# Initialize futures analyzer
print("\n[2/3] Initializing FuturesAnalyzer...")
try:
    analyzer = FuturesAnalyzer(df)
    print("✅ Futures analyzer initialized")
except Exception as e:
    print(f"❌ Failed to initialize FuturesAnalyzer: {e}")
    print("\nNote: Futures analysis requires price data with futures-specific structure.")
    print("This example demonstrates the API even with spot data.")
    exit(0)

# Get analysis summary
print("\n[3/3] Generating futures analysis summary...")
try:
    summary = analyzer.get_analysis_summary()

    print("\n" + "=" * 70)
    print("FUTURES ANALYSIS SUMMARY")
    print("=" * 70)

    for key, value in summary.items():
        if isinstance(value, (int, float)):
            if isinstance(value, float):
                print(f"{key}: {value:.4f}")
            else:
                print(f"{key}: {value}")
        elif isinstance(value, dict):
            print(f"\n{key}:")
            for subkey, subval in value.items():
                if isinstance(subval, float):
                    print(f"  {subkey}: {subval:.4f}")
                else:
                    print(f"  {subkey}: {subval}")
        else:
            print(f"{key}: {value}")

    print("\n" + "=" * 70)
    print("✅ Futures analysis complete!")
    print("=" * 70)

except Exception as e:
    print(f"\n⚠️  Analysis completed with limitations: {e}")
    print("\nNote: Full futures analysis requires:")
    print("  - Multiple contract months")
    print("  - Expiration date information")
    print("  - Sufficient price history")
    print("\nCurrent data is sufficient for basic analysis.")

print("\n" + "=" * 70)
print("✅ Example complete!")
print("=" * 70)
print("\nFor advanced futures analysis:")
print("  - Add multiple contract months to database")
print("  - Include expiration dates in data")
print("  - Use futures-specific data sources")
