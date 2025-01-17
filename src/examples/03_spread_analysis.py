# examples/03_spread_analysis.py
import duckdb
import polars as pl
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import numpy as np

class SpreadAnalyzer:
    """Analyze price spreads between energy products."""
    
    def __init__(self, db_path: str = "energy.db"):
        """Initialize the spread analyzer."""
        self.conn = duckdb.connect(db_path)
        
        # Common energy spreads and their descriptions
        self.COMMON_SPREADS = {
            "CRACK_SPREAD": {
                "long": ["RB=F", "HO=F"],  # Gasoline and Heating Oil
                "short": ["CL=F"],          # Crude Oil
                "description": "3:2:1 Crack Spread"
            },
            "WTI_BRENT": {
                "long": ["CL=F"],           # WTI Crude
                "short": ["BZ=F"],          # Brent Crude
                "description": "WTI-Brent Spread"
            },
            "NAT_GAS_EQUITY": {
                "long": ["NG=F"],           # Natural Gas Futures
                "short": ["UNG"],           # Natural Gas ETF
                "description": "Natural Gas Futures-ETF Spread"
            }
        }
    
    def get_spread_data(self, symbols: list[str], days: int = 365) -> pl.DataFrame:
        """Get historical price data for multiple symbols."""
        symbols_str = ", ".join(f"'{s}'" for s in symbols)
        query = f"""
        WITH prices AS (
            SELECT 
                date,
                symbol,
                close
            FROM securities
            WHERE symbol IN ({symbols_str})
                AND date >= CURRENT_DATE - {days}
            ORDER BY date
        )
        PIVOT prices ON symbol USING first(close)
        """
        return pl.from_arrow(self.conn.execute(query).arrow())
    
    def calculate_spread(self, df: pl.DataFrame, long_symbols: list[str], 
                        short_symbols: list[str]) -> pl.DataFrame:
        """Calculate spread between long and short positions."""
        # Calculate the average price for long and short positions
        long_expr = sum(pl.col(sym) for sym in long_symbols) / len(long_symbols)
        short_expr = sum(pl.col(sym) for sym in short_symbols) / len(short_symbols)
        
        return df.with_columns([
            long_expr.alias("long_price"),
            short_expr.alias("short_price"),
            (long_expr - short_expr).alias("spread")
        ])
    
    def calculate_spread_stats(self, spread_df: pl.DataFrame) -> dict:
        """Calculate statistical measures for the spread."""
        spread = spread_df["spread"]
        return {
            "current": float(spread.tail(1)[0]),
            "mean": float(spread.mean()),
            "std": float(spread.std()),
            "min": float(spread.min()),
            "max": float(spread.max()),
            "zscore": float((spread.tail(1)[0] - spread.mean()) / spread.std()),
            "percentile": float(np.percentile(spread, 50))  # Current percentile
        }
    
    def plot_spread(self, df: pl.DataFrame, long_symbols: list[str], 
                   short_symbols: list[str], title: str) -> go.Figure:
        """Create spread analysis visualization."""
        fig = make_subplots(rows=2, cols=1, 
                           shared_xaxes=True,
                           vertical_spacing=0.03,
                           row_heights=[0.7, 0.3])
        
        # Plot individual prices
        for symbol in long_symbols:
            fig.add_trace(
                go.Scatter(x=df["date"], y=df[symbol], 
                          name=f"{symbol} (Long)",
                          line=dict(color="green")),
                row=1, col=1
            )
        
        for symbol in short_symbols:
            fig.add_trace(
                go.Scatter(x=df["date"], y=df[symbol], 
                          name=f"{symbol} (Short)",
                          line=dict(color="red")),
                row=1, col=1
            )
        
        # Plot spread
        fig.add_trace(
            go.Scatter(x=df["date"], y=df["spread"],
                      name="Spread",
                      line=dict(color="blue")),
            row=2, col=1
        )
        
        # Add mean and standard deviation bands
        mean_spread = df["spread"].mean()
        std_spread = df["spread"].std()
        
        fig.add_hline(y=mean_spread, line_dash="dash", line_color="gray", 
                     name="Mean", row=2, col=1)
        fig.add_hline(y=mean_spread + std_spread, line_dash="dash", 
                     line_color="red", name="+1 STD", row=2, col=1)
        fig.add_hline(y=mean_spread - std_spread, line_dash="dash", 
                     line_color="red", name="-1 STD", row=2, col=1)
        
        fig.update_layout(
            title=title,
            yaxis_title="Price",
            yaxis2_title="Spread",
            height=800,
            showlegend=True
        )
        
        return fig
    
    def analyze_spread(self, spread_name: str) -> tuple[pl.DataFrame, dict, go.Figure]:
        """Analyze a predefined spread."""
        if spread_name not in self.COMMON_SPREADS:
            raise ValueError(f"Unknown spread: {spread_name}")
        
        spread_config = self.COMMON_SPREADS[spread_name]
        long_symbols = spread_config["long"]
        short_symbols = spread_config["short"]
        all_symbols = long_symbols + short_symbols
        
        # Get price data
        df = self.get_spread_data(all_symbols)
        
        # Calculate spread
        df = self.calculate_spread(df, long_symbols, short_symbols)
        
        # Calculate statistics
        stats = self.calculate_spread_stats(df)
        
        # Create visualization
        fig = self.plot_spread(df, long_symbols, short_symbols, 
                             spread_config["description"])
        
        return df, stats, fig

def main():
    """Example usage of spread analysis."""
    analyzer = SpreadAnalyzer()
    
    # Analyze crack spread
    print("\nAnalyzing 3:2:1 Crack Spread...")
    df, stats, fig = analyzer.analyze_spread("CRACK_SPREAD")
    fig.write_html("crack_spread_analysis.html")
    print("\nCrack Spread Statistics:")
    print(f"Current Spread: {stats['current']:.2f}")
    print(f"Mean: {stats['mean']:.2f}")
    print(f"Z-Score: {stats['zscore']:.2f}")
    print(f"Percentile: {stats['percentile']:.2f}")
    
    # Analyze WTI-Brent spread
    print("\nAnalyzing WTI-Brent Spread...")
    df, stats, fig = analyzer.analyze_spread("WTI_BRENT")
    fig.write_html("wti_brent_spread_analysis.html")
    print("\nWTI-Brent Spread Statistics:")
    print(f"Current Spread: {stats['current']:.2f}")
    print(f"Mean: {stats['mean']:.2f}")
    print(f"Z-Score: {stats['zscore']:.2f}")
    print(f"Percentile: {stats['percentile']:.2f}")

if __name__ == "__main__":
    main()