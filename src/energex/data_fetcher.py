# src/energex/data_fetcher.py
import yfinance as yf
import polars as pl
from datetime import datetime, timedelta
import pytz

class EnergyDataFetcher:
    ENERGY_SYMBOLS = {
        'crude': {'ticker': 'CL=F', 'name': 'Crude Oil Futures'},
        'brent': {'ticker': 'BZ=F', 'name': 'Brent Crude Oil Futures'},
        'gas': {'ticker': 'NG=F', 'name': 'Natural Gas Futures'}
    }
    
    def __init__(self):
        # Initialize with UTC timezone
        self.end_time = datetime.now(pytz.UTC)
        self.start_time = self.end_time - timedelta(days=1)
        
    def get_commodity_data(self, commodity: str) -> pl.DataFrame:
        """
        Fetch intraday commodity data.
        Args:
            commodity: The commodity key (crude, brent, gas)
        Returns:
            Polars DataFrame with standardized columns
        """
        ticker = self.ENERGY_SYMBOLS[commodity]['ticker']
        print(f"Downloading {commodity} ({ticker}) data...")
        
        try:
            # Download data using the actual ticker symbol
            data = yf.download(
                ticker,
                start=self.start_time,
                end=self.end_time,
                interval='1m'
            )
            
            if data.empty:
                print(f"No data returned for {commodity} ({ticker})")
                return pl.DataFrame()
                
            # Reset index and handle multi-index columns
            df = data.reset_index()
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            
            # Convert to Polars DataFrame and add symbol
            df = pl.from_pandas(df)
            df = df.with_columns(pl.lit(ticker).alias('Symbol'))
            
            # Sort and select columns in specific order
            df = (df
                .sort(['Symbol', 'Datetime'])
                .select([
                    'Datetime',
                    'Symbol',
                    'Open',
                    'High',
                    'Low',
                    'Close',
                    'Volume'
                ])
            )
            
            print(f"Got {len(df)} rows for {commodity} ({ticker})")
            return df
            
        except Exception as e:
            print(f"Error downloading {commodity} ({ticker}): {str(e)}")
            return pl.DataFrame()

    def fetch_all_commodities(self) -> pl.DataFrame:
        """Fetch and combine data for all commodities."""
        dfs = []
        
        for commodity in self.ENERGY_SYMBOLS:
            try:
                df = self.get_commodity_data(commodity)
                if not df.is_empty():
                    dfs.append(df)
            except Exception as e:
                print(f"Error processing {commodity}: {str(e)}")
        
        if not dfs:
            return pl.DataFrame()
            
        # Combine all dataframes
        combined_data = pl.concat(dfs)
        
        # Clean and organize final dataset
        final_data = (
            combined_data
            .sort(['Symbol', 'Datetime'])
            .select([
                'Datetime',
                'Symbol',
                'Open',
                'High',
                'Low',
                'Close',
                'Volume'
            ])
        )
        
        return final_data

    def fetch_all_commodities(self) -> dict[str, pl.DataFrame]:
        """Fetch intraday data for all commodity symbols."""
        return {
            symbol: self.get_commodity_data(symbol)
            for symbol in self.ENERGY_SYMBOLS.keys()
        }