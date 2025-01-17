import yfinance as yf
import polars as pl
from datetime import datetime, timedelta

class EnergyDataFetcher:
    ENERGY_SYMBOLS = {
        "CL=F": "Crude Oil Futures",
        "NG=F": "Natural Gas Futures",
        "HO=F": "Heating Oil Futures",
        "RB=F": "RBOB Gasoline Futures",
        "BZ=F": "Brent Crude Oil Futures",
        "XLE": "Energy Select Sector SPDR Fund",  # Energy sector ETF
        "USO": "United States Oil Fund",          # Oil ETF
        "UNG": "United States Natural Gas Fund"   # Natural Gas ETF
    }
    
    def __init__(self):
        self.start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        self.end_date = datetime.now().strftime('%Y-%m-%d')
    
    def fetch_security(self, symbol: str) -> pl.DataFrame:
        """Fetch historical data for a single security."""
        data = yf.download(symbol, start=self.start_date, end=self.end_date)
        
        # Handle MultiIndex columns by flattening them
        data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]
        df = pl.from_pandas(data.reset_index())
        
        print(f"Original columns in DataFrame: {df.columns}")
        
        # Start with basic columns that should always exist
        processed_df = (df
            .with_columns([
                pl.lit(symbol).alias("symbol"),
                pl.col("Date").cast(pl.Date).alias("date")
            ])
            .rename({
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            }))
        
        # Add adj_close if it exists, otherwise use close
        if 'Adj Close' in df.columns:
            processed_df = processed_df.with_columns([
                pl.col('Adj Close').alias('adj_close')
            ])
        else:
            processed_df = processed_df.with_columns([
                pl.col('close').alias('adj_close')
            ])
            print(f"Note: No Adj Close for {symbol}, using regular close price")
        
        # Drop the original Date column and ensure column order
        processed_df = processed_df.drop("Date")
        
        print(f"Final columns: {processed_df.columns}")
        return processed_df

    
    def fetch_all_securities(self) -> dict[str, pl.DataFrame]:
        """Fetch historical data for all energy securities."""
        return {
            symbol: self.fetch_security(symbol)
            for symbol in self.ENERGY_SYMBOLS.keys()
        }
    
    def fetch_options(self, symbol: str) -> pl.DataFrame:
        """Fetch options data for a security."""
        ticker = yf.Ticker(symbol)
        options_data = []
        
        for date in ticker.options:
            opt = ticker.option_chain(date)
            
            # Process calls
            calls = pl.from_pandas(opt.calls)
            calls = calls.with_columns([
                pl.lit("call").alias("option_type"),
                pl.lit(date).alias("expiration"),
                pl.lit(symbol).alias("symbol")
            ])
            
            # Process puts
            puts = pl.from_pandas(opt.puts)
            puts = puts.with_columns([
                pl.lit("put").alias("option_type"),
                pl.lit(date).alias("expiration"),
                pl.lit(symbol).alias("symbol")
            ])
            
            options_data.extend([calls, puts])
        
        return pl.concat(options_data)