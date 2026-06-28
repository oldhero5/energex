# examples/01_data_quality_analysis.py
"""
Data Quality Analysis Example

Demonstrates how to check data quality and detect anomalies
in energy futures price data.

Prerequisites:
    Run 00_setup_data.py first to populate the database

Usage:
    python src/examples/01_data_quality_analysis.py
"""

import plotly.express as px
import polars as pl

from energex import DataQualityChecker, EnergyDatabase

print("=" * 70)
print("ENERGEX - Data Quality Analysis Example")
print("=" * 70)

# Connect to database
print("\n[1/5] Connecting to database...")
db = EnergyDatabase()

# Get recent data (last 24 hours)
query = """
SELECT *
FROM intraday_prices
WHERE Datetime >= CURRENT_TIMESTAMP - INTERVAL '24' HOUR
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
print(f"   Date range: {df['Datetime'].min()} to {df['Datetime'].max()}")

# Initialize quality checker
print("\n[2/5] Initializing DataQualityChecker...")
checker = DataQualityChecker(df)
print("✅ Quality checker initialized")

# Check for price gaps
print("\n[3/5] Checking for price gaps...")
gaps = checker.check_price_gaps(threshold_pct=0.5)
if len(gaps) > 0:
    print(f"⚠️  Found {len(gaps)} significant price gaps:")
    print(gaps.select(['Datetime', 'Symbol', 'gap_pct', 'prev_close', 'current_open']).head(5))
else:
    print("✅ No significant price gaps detected")

# Check for volume anomalies
print("\n[4/5] Checking for volume anomalies...")
vol_anomalies = checker.check_volume_anomalies(z_score_threshold=3.0)
if len(vol_anomalies) > 0:
    print(f"⚠️  Found {len(vol_anomalies)} volume anomalies:")
    print(vol_anomalies.select(['Datetime', 'Symbol', 'Volume', 'volume_z_score']).head(5))
else:
    print("✅ No volume anomalies detected")

# Get overall quality metrics
print("\n[5/5] Calculating overall quality metrics...")
metrics = checker.check_tick_quality()
print("\n" + "=" * 70)
print("QUALITY METRICS SUMMARY")
print("=" * 70)
for metric, value in metrics.items():
    if isinstance(value, float):
        print(f"{metric}: {value:.4f}")
    else:
        print(f"{metric}: {value}")

# Visualize volume anomalies if any
if len(vol_anomalies) > 0:
    print("\n[Visualization] Creating volume anomalies chart...")
    fig = px.scatter(
        vol_anomalies.to_pandas(),
        x='Datetime',
        y='volume_z_score',
        color='Symbol',
        title='Volume Anomalies by Symbol (Z-Score > 3.0)',
        labels={'volume_z_score': 'Volume Z-Score'},
        hover_data=['Volume']
    )
    fig.write_html("quality_volume_anomalies.html")
    print("✅ Saved: quality_volume_anomalies.html")

print("\n" + "=" * 70)
print("✅ Data quality analysis complete!")
print("=" * 70)
