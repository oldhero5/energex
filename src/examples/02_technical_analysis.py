# examples/02_technical_analysis.py
import duckdb
import polars as pl
from plotly.subplots import make_subplots
import plotly.graph_objects as go

class TechnicalAnalyzer:
    def __init__(self, db_path: str = "energy.db"):
        self.conn = duckdb.connect(db_path)
    
    def get_data(self, symbol: str, days: int = 365) -> pl.DataFrame:
        """Get base data with proper types."""
        query = """
            SELECT 
                date::DATE as date,
                CAST(close as DOUBLE) as close,
                CAST(volume as BIGINT) as volume
            FROM securities 
            WHERE symbol = ?
                AND date >= CURRENT_DATE - ?::INTEGER
            ORDER BY date
        """
        return pl.from_arrow(self.conn.execute(query, [symbol, days]).arrow())
    
    def add_moving_averages(self, df: pl.DataFrame) -> pl.DataFrame:
        """Add moving average calculations."""
        return df.with_columns([
            pl.col("close").cast(pl.Float64).rolling_mean(
                window_size=window,
                min_periods=1
            ).alias(f"ma{window}")
            for window in [20, 50, 200]
        ])
    
    def add_price_changes(self, df: pl.DataFrame) -> pl.DataFrame:
        """Add daily price changes."""
        return df.with_columns([
            pl.col("close").diff().cast(pl.Float64).alias("price_change")
        ])
    
    def add_rsi(self, df: pl.DataFrame, periods: int = 14) -> pl.DataFrame:
        """Add RSI calculation."""
        # First add gains and losses
        df = df.with_columns([
            pl.when(pl.col("price_change") > 0)
              .then(pl.col("price_change"))
              .otherwise(0.0)
              .alias("gains"),
            pl.when(pl.col("price_change") < 0)
              .then(-1 * pl.col("price_change"))
              .otherwise(0.0)
              .alias("losses")
        ])
        
        # Calculate smoothed averages
        df = df.with_columns([
            pl.col("gains").rolling_mean(
                window_size=periods,
                min_periods=1
            ).alias("avg_gains"),
            pl.col("losses").rolling_mean(
                window_size=periods,
                min_periods=1
            ).alias("avg_losses")
        ])
        
        # Calculate RSI avoiding division by zero
        df = df.with_columns([
            pl.when(pl.col("avg_losses") != 0.0)
              .then(100.0 - (100.0 / (1.0 + pl.col("avg_gains") / pl.col("avg_losses"))))
              .otherwise(100.0)
              .alias("rsi")
        ])
        
        return df
    
    def add_signals(self, df: pl.DataFrame) -> pl.DataFrame:
        """Add trading signals."""
        return df.with_columns([
            # Golden Cross - need to use parentheses properly with &
            ((pl.col("ma50") > pl.col("ma200")) & 
             (pl.col("ma50").shift(1) <= pl.col("ma200").shift(1)))
            .alias("golden_cross"),
            
            # Death Cross
            ((pl.col("ma50") < pl.col("ma200")) & 
             (pl.col("ma50").shift(1) >= pl.col("ma200").shift(1)))
            .alias("death_cross"),
            
            # RSI Signals
            (pl.col("rsi") < 30).alias("oversold"),
            (pl.col("rsi") > 70).alias("overbought")
        ])
    
    def plot_analysis(self, df: pl.DataFrame, symbol: str) -> go.Figure:
        """Create technical analysis plot."""
        fig = make_subplots(rows=2, cols=1, 
                           shared_xaxes=True,
                           vertical_spacing=0.03,
                           row_heights=[0.7, 0.3])

        # Price and MA lines
        fig.add_trace(go.Scatter(
            x=df["date"], 
            y=df["close"], 
            name='Price',
            line=dict(color='black')
        ), row=1, col=1)
        
        for ma in ["ma20", "ma50", "ma200"]:
            fig.add_trace(go.Scatter(
                x=df["date"], 
                y=df[ma], 
                name=ma.upper(),
                line=dict(color='blue' if ma == "ma20" else 
                         'orange' if ma == "ma50" else 'red')
            ), row=1, col=1)

        # RSI
        fig.add_trace(go.Scatter(
            x=df["date"], 
            y=df["rsi"], 
            name='RSI',
            line=dict(color='purple')
        ), row=2, col=1)
        
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

        fig.update_layout(
            title=f'{symbol} Technical Analysis',
            yaxis_title='Price',
            yaxis2_title='RSI',
            xaxis2_title='Date',
            showlegend=True,
            height=800
        )

        return fig
    
    def analyze(self, symbol: str, days: int = 365):
        """Perform complete technical analysis."""
        try:
            print(f"Starting analysis for {symbol}")
            
            # Get base data
            df = self.get_data(symbol, days)
            print(f"Got {len(df)} rows of data")
            print("Initial schema:", df.schema)
            
            # Add indicators step by step
            print("\nAdding moving averages...")
            df = self.add_moving_averages(df)
            print("Moving averages added successfully")
            
            print("\nAdding price changes...")
            df = self.add_price_changes(df)
            print("Price changes schema:", df.schema)
            
            print("\nCalculating RSI...")
            df = self.add_rsi(df)
            print("RSI schema:", df.schema)
            
            print("\nGenerating signals...")
            df = self.add_signals(df)
            print("Signals added successfully")
            print("Final schema:", df.schema)
            
            # Get recent signals
            signals = df.filter(
                pl.col("golden_cross") | 
                pl.col("death_cross") | 
                pl.col("oversold") | 
                pl.col("overbought")
            ).tail(5)
            
            print("\nAnalysis complete!")
            
            # Create plot
            fig = self.plot_analysis(df, symbol)
            
            return df, signals, fig
            
        except Exception as e:
            print(f"Error in analyze method: {str(e)}")
            print(f"Error occurred after processing {len(df) if 'df' in locals() else 0} rows")
            raise
        
        # Create plot
        fig = self.plot_analysis(df, symbol)
        
        return df, signals, fig

def main():
    analyzer = TechnicalAnalyzer()
    
    try:
        df, signals, fig = analyzer.analyze("CL=F")
        
        # Save plot
        output_path = "crude_oil_analysis.html"
        fig.write_html(output_path)
        print(f"\nAnalysis chart saved to {output_path}")
        
        # Print signals
        print("\nRecent Trading Signals:")
        print(signals)
        
    except Exception as e:
        print(f"Error during analysis: {str(e)}")
        raise

if __name__ == "__main__":
    main()