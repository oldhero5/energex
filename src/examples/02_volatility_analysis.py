# examples/02_volatility_analysis.py
"""
Volatility Analysis Example

Demonstrates multiple volatility calculation methods for
energy futures contracts.

Prerequisites:
    Run 00_setup_data.py first to populate the database

Usage:
    python src/examples/02_volatility_analysis.py
"""

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from energex import EnergyDatabase, VolatilityAnalyzer

print("=" * 70)
print("ENERGEX - Volatility Analysis Example")
print("=" * 70)

# Connect to database
print("\n[1/4] Connecting to database...")
db = EnergyDatabase()

# Get recent data (last 7 days for better volatility calc)
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

# Initialize volatility analyzer
print("\n[2/4] Initializing VolatilityAnalyzer...")
analyzer = VolatilityAnalyzer(df)
print("✅ Volatility analyzer initialized")

# Calculate all volatility metrics
print("\n[3/4] Calculating volatility metrics...")
results = analyzer.calculate_volatility_metrics()
print(f"✅ Calculated metrics for {len(results)} data points")

# Display summary statistics
print("\n[4/4] Generating summary statistics...")
for symbol in results['Symbol'].unique():
    symbol_data = results.filter(pl.col('Symbol') == symbol)

    print(f"\n{symbol} Volatility Summary:")
    print(f"  Realized Vol (avg):    {symbol_data['realized_vol'].mean():.4f}")
    print(f"  Parkinson Vol (avg):   {symbol_data['parkinson_vol'].mean():.4f}")
    print(f"  Garman-Klass Vol (avg): {symbol_data['garman_klass_vol'].mean():.4f}")
    print(f"  Intraday Range % (avg): {symbol_data['intraday_range_pct'].mean():.2f}%")

    # Create visualization
    print(f"\n  Creating visualization for {symbol}...")
    symbol_results = results.filter(pl.col('Symbol') == symbol)

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=(
            f'{symbol} - Price & Volatility',
            'Volatility Ratios',
            'Intraday Range %'
        )
    )

    # Price and volatility
    fig.add_trace(
        go.Scatter(
            x=symbol_results['Datetime'],
            y=symbol_results['Close'],
            name='Price',
            line={'color': 'blue'}
        ),
        row=1, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=symbol_results['Datetime'],
            y=symbol_results['realized_vol'],
            name='Realized Vol',
            line={'color': 'red', 'dash': 'dot'},
            yaxis='y2'
        ),
        row=1, col=1
    )

    # Volatility ratios
    fig.add_trace(
        go.Scatter(
            x=symbol_results['Datetime'],
            y=symbol_results['vol_ratio_pk_rv'],
            name='Parkinson/Realized'
        ),
        row=2, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=symbol_results['Datetime'],
            y=symbol_results['vol_ratio_gk_rv'],
            name='Garman-Klass/Realized'
        ),
        row=2, col=1
    )

    # Intraday range
    fig.add_trace(
        go.Scatter(
            x=symbol_results['Datetime'],
            y=symbol_results['intraday_range_pct'],
            name='Intraday Range %',
            fill='tozeroy'
        ),
        row=3, col=1
    )

    fig.update_layout(
        height=900,
        title=f'Volatility Analysis - {symbol}',
        showlegend=True
    )

    filename = f"volatility_{symbol.replace('=', '')}.html"
    fig.write_html(filename)
    print(f"  ✅ Saved: {filename}")

print("\n" + "=" * 70)
print("✅ Volatility analysis complete!")
print("=" * 70)
