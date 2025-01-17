from energex.database import EnergyDatabase
from energex.data_fetcher import EnergyDataFetcher

def main():
    # Initialize components
    db = EnergyDatabase()
    fetcher = EnergyDataFetcher()
    
    # Fetch and store securities data
    securities_data = fetcher.fetch_all_securities()
    for symbol, df in securities_data.items():
        description = fetcher.ENERGY_SYMBOLS[symbol]
        db.insert_securities_data(df, "futures", description)
    
    # Fetch and store options data
    for symbol in fetcher.ENERGY_SYMBOLS:
        try:
            options_df = fetcher.fetch_options(symbol)
            if not options_df.is_empty():
                db.conn.execute("INSERT INTO options SELECT * FROM options_df")
                db.conn.commit()
        except Exception as e:
            print(f"Error fetching options for {symbol}: {e}")

if __name__ == "__main__":
    main()
