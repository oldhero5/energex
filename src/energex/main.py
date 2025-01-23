# src/energex/main.py
from energex.database import EnergyDatabase
from energex.data_fetcher import EnergyDataFetcher
from datetime import datetime

def update_intraday_data():
    """Update intraday data for all commodities."""
    db = EnergyDatabase()
    fetcher = EnergyDataFetcher()
    
    print(f"\nStarting intraday data update at {datetime.now()}")
    
    successful = []
    failed = []
    
    for symbol in fetcher.ENERGY_SYMBOLS:
        try:
            print(f"\nProcessing {symbol}...")
            df = fetcher.get_commodity_data(symbol)
            
            if not df.is_empty():
                db.insert_intraday_data(df)
                successful.append(symbol)
            else:
                failed.append((symbol, "No data returned"))
                
        except Exception as e:
            print(f"Error processing {symbol}: {str(e)}")
            failed.append((symbol, str(e)))
    
    # Print summary
    print("\nUpdate Summary:")
    print(f"Successfully processed: {len(successful)} symbols")
    if successful:
        print("Successful symbols:", ", ".join(successful))
    if failed:
        print("\nFailed symbols:")
        for symbol, error in failed:
            print(f"- {symbol}: {error}")

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Energy commodity data collector')
    parser.add_argument('--check', action='store_true',
                       help='Check database schema and tables')
    
    args = parser.parse_args()
    
    if args.check:
        db = EnergyDatabase()
        db.conn.execute("DESCRIBE intraday_prices").show()
    else:
        update_intraday_data()

if __name__ == "__main__":
    main()