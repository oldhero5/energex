# examples/01_basic_queries.py
import duckdb
import polars as pl
from datetime import datetime, timedelta

class EnergyQueryTool:
    def __init__(self, db_path: str = "energy.db"):
        """Initialize connection to the database."""
        self.conn = duckdb.connect(db_path)
        
    def get_latest_prices(self):
        """Get the most recent prices for all symbols."""
        query = """
        WITH ranked AS (
            SELECT 
                symbol,
                date,
                close,
                volume,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
            FROM securities
        )
        SELECT 
            symbol,
            date,
            close,
            volume
        FROM ranked
        WHERE rn = 1
        ORDER BY symbol
        """
        return pl.from_arrow(self.conn.execute(query).arrow())
    
    def get_daily_returns(self, symbol: str, days: int = 30):
        """Calculate daily returns for a symbol."""
        query = """
        SELECT 
            date,
            symbol,
            close,
            (close - LAG(close) OVER (ORDER BY date)) / LAG(close) OVER (ORDER BY date) * 100 as daily_return
        FROM securities
        WHERE symbol = ?
        AND date >= CURRENT_DATE - ?
        ORDER BY date
        """
        return pl.from_arrow(self.conn.execute(query, [symbol, days]).arrow())
    
    def get_volume_analysis(self, symbol: str, days: int = 30):
        """Analyze trading volume patterns."""
        query = """
        SELECT 
            date,
            volume,
            AVG(volume) OVER (
                ORDER BY date 
                ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
            ) as avg_5day_volume
        FROM securities
        WHERE symbol = ?
        AND date >= CURRENT_DATE - ?
        ORDER BY date
        """
        return pl.from_arrow(self.conn.execute(query, [symbol, days]).arrow())
    
    def get_price_summary(self, days: int = 30):
        """Get price summary statistics for all symbols."""
        query = """
        SELECT 
            symbol,
            MIN(close) as min_price,
            MAX(close) as max_price,
            AVG(close) as avg_price,
            FIRST_VALUE(close) OVER (PARTITION BY symbol ORDER BY date DESC) as last_price,
            COUNT(*) as trading_days
        FROM securities
        WHERE date >= CURRENT_DATE - ?
        GROUP BY symbol
        ORDER BY symbol
        """
        return pl.from_arrow(self.conn.execute(query, [days]).arrow())

def main():
    # Initialize the query tool
    tool = EnergyQueryTool()
    
    # Get and print latest prices
    print("\nLatest Prices:")
    print(tool.get_latest_prices())
    
    # Get and print returns for crude oil
    print("\nCrude Oil Daily Returns:")
    print(tool.get_daily_returns("CL=F"))
    
    # Get and print volume analysis for natural gas
    print("\nNatural Gas Volume Analysis:")
    print(tool.get_volume_analysis("NG=F"))
    
    # Get and print price summary
    print("\nPrice Summary (Last 30 Days):")
    print(tool.get_price_summary())

if __name__ == "__main__":
    main()