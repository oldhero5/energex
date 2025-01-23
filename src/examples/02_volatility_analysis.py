# examples/02_volatility_analysis.py
import polars as pl
from energex.database import EnergyDatabase
from energex.analysis.volatility import VolatilityAnalyzer
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

def analyze_volatility():
    """Example of using the VolatilityAnalyzer."""
    # Connect to database
    db = EnergyDatabase()
    
    # Get recent data
    query = """
    SELECT *
    FROM intraday_prices
    WHERE Datetime >= CURRENT_DATE - INTERVAL '1' DAY
    ORDER BY Symbol, Datetime
    """
    df = pl.from_arrow(db.conn.execute(query).arrow())
    
    print(f"Analyzing volatility for {len(df)} records...")
    
    # Initialize volatility analyzer
    analyzer = VolatilityAnalyzer(df)
    
    # Calculate all volatility metrics
    results = analyzer.calculate_volatility_metrics()
    
    # Create visualization
    for symbol in results['Symbol'].unique():
        symbol_data = results.filter(pl.col('Symbol') == symbol)
        
        fig = make_subplots(rows=3, cols=1,
                           shared_xaxes=True,
                           vertical_spacing=0.05,
                           subplot_titles=('Price & Volatility',
                                         'Volatility Ratios',
                                         'Intraday Range'))
        
        # Price and volatility
        fig.add_trace(
            go.Scatter(x=symbol_data['Datetime'],
                      y=symbol_data['Close'],
                      name='Price'),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(x=symbol_data['Datetime'],
                      y=symbol_data['realized_vol'],
                      name='Realized Vol'),
            row=1, col=1
        )
        
        # Volatility ratios
        fig.add_trace(
            go.Scatter(x=symbol_data['Datetime'],
                      y=symbol_data['vol_ratio_pk_rv'],
                      name='Parkinson/Realized'),
            row=2, col=1
        )
        
        fig.add_trace(
            go.Scatter(x=symbol_data['Datetime'],
                      y=symbol_data['vol_ratio_gk_rv'],
                      name='Garman-Klass/Realized'),
            row=2, col=1
        )
        
        # Intraday range
        fig.add_trace(
            go.Scatter(x=symbol_data['Datetime'],
                      y=symbol_data['intraday_range_pct'],
                      name='Intraday Range %'),
            row=3, col=1
        )
        
        fig.update_layout(height=900,
                         title=f'Volatility Analysis - {symbol}')
        
        fig.write_html(f"volatility_{symbol}.html")
        print(f"\nVisualization saved as 'volatility_{symbol}.html'")
        
        # Print summary statistics
        print(f"\nSummary Statistics for {symbol}:")
        print("Average Realized Volatility:",
              symbol_data['realized_vol'].mean())
        print("Average Parkinson Volatility:",
              symbol_data['parkinson_vol'].mean())
        print("Average Garman-Klass Volatility:",
              symbol_data['garman_klass_vol'].mean())
        print("Average Intraday Range %:",
              symbol_data['intraday_range_pct'].mean())

if __name__ == "__main__":
    analyze_volatility()