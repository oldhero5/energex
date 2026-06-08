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

# Compute an inter-contract spread between two stored symbols.
print("\n[3/3] Computing cross-symbol spread (term-structure proxy)...")
symbols = df["Symbol"].unique().to_list()
if len(symbols) < 2:
    print(f"⚠️  Need >= 2 symbols for a spread; found {symbols}.")
    exit(0)

front, back = symbols[0], symbols[1]
spread = analyzer.calculate_term_structure(front, back)

print("\n" + "=" * 70)
print(f"{front} vs {back} SPREAD (most recent rows)")
print("=" * 70)
print(spread.select(["Datetime", "spread", "spread_pct"]).tail(5))

print(
    "\nNote: true term-structure / roll-yield / implied-rate analytics need dated\n"
    "contract months + a spot leg (see ASSESSMENT.md R8); those methods raise\n"
    "NotImplementedError until a licensed dated-contract source is wired."
)
print("\n" + "=" * 70)
print("✅ Futures analysis complete!")
print("=" * 70)

print("\n" + "=" * 70)
print("✅ Example complete!")
print("=" * 70)
print("\nFor advanced futures analysis:")
print("  - Add multiple contract months to database")
print("  - Include expiration dates in data")
print("  - Use futures-specific data sources")
