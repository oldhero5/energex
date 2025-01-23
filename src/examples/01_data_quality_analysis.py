# examples/01_data_quality_analysis.py
import polars as pl
from energex.database import EnergyDatabase
from energex.analysis.quality import DataQualityChecker
import plotly.express as px
from datetime import datetime, timedelta

def analyze_data_quality():
    """Example of using the DataQualityChecker."""
    # Connect to database
    db = EnergyDatabase()
    
    # Get today's data
    query = """
    SELECT *
    FROM intraday_prices
    WHERE Datetime >= CURRENT_DATE
    ORDER BY Symbol, Datetime
    """
    df = pl.from_arrow(db.conn.execute(query).arrow())
    
    print(f"Analyzing {len(df)} records...")
    
    # Initialize quality checker
    checker = DataQualityChecker(df)
    
    # 1. Check for price gaps
    print("\nChecking for price gaps...")
    gaps = checker.check_price_gaps(threshold_pct=0.5)
    print(f"Found {len(gaps)} significant price gaps:")
    print(gaps)
    
    # 2. Check for volume anomalies
    print("\nChecking for volume anomalies...")
    vol_anomalies = checker.check_volume_anomalies(z_score_threshold=3.0)
    print(f"Found {len(vol_anomalies)} volume anomalies:")
    print(vol_anomalies)
    
    # 3. Check for price reversals
    print("\nChecking for price reversals...")
    reversals = checker.check_price_reversals(threshold_pct=1.0)
    print(f"Found {len(reversals)} significant price reversals:")
    print(reversals)
    
    # 4. Get overall quality metrics
    print("\nCalculating overall quality metrics...")
    metrics = checker.check_tick_quality()
    print("\nQuality Metrics Summary:")
    for metric, value in metrics.items():
        print(f"{metric}: {value}")
    
    # 5. Visualize anomalies
    if not vol_anomalies.is_empty():
        fig = px.scatter(vol_anomalies.to_pandas(),
                        x='Datetime',
                        y='volume_z_score',
                        color='Symbol',
                        title='Volume Anomalies by Symbol')
        fig.write_html("volume_anomalies.html")
        print("\nVisualization saved as 'volume_anomalies.html'")

if __name__ == "__main__":
    analyze_data_quality()