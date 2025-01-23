# src/energex/database.py
import duckdb
import polars as pl
from pathlib import Path

class EnergyDatabase:
    def __init__(self, db_path: str = "energy.db"):
        self.db_path = Path(db_path)
        self.conn = duckdb.connect(str(self.db_path))
        self._init_tables()
    
    def _init_tables(self):
        """Initialize database tables."""
        # Drop existing tables
        self.conn.execute("DROP TABLE IF EXISTS intraday_prices")
        
        # Create intraday prices table
        self.conn.execute("""
            CREATE TABLE intraday_prices (
                Datetime TIMESTAMP,
                Symbol VARCHAR,
                Open DOUBLE,
                High DOUBLE,
                Low DOUBLE,
                Close DOUBLE,
                Volume BIGINT,
                
                -- Add constraints
                CONSTRAINT pk_intraday PRIMARY KEY (Symbol, Datetime)
            )
        """)
        
        # Create index for faster queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_intraday_symbol_datetime 
            ON intraday_prices(Symbol, Datetime)
        """)
    
    def insert_intraday_data(self, df: pl.DataFrame):
        """Insert intraday price data."""
        if df.is_empty():
            print("No data to insert")
            return
            
        print(f"Inserting {len(df)} rows with schema:")
        print(df.schema)
        
        try:
            # Start transaction
            self.conn.execute("BEGIN TRANSACTION")
            
            # Delete existing data for all symbols in the dataframe
            symbols = df.select(pl.col("Symbol").unique()).to_series().to_list()
            placeholders = ", ".join(["?" for _ in symbols])
            self.conn.execute(f"DELETE FROM intraday_prices WHERE Symbol IN ({placeholders})", symbols)
            
            # Insert new data
            self.conn.execute("INSERT INTO intraday_prices SELECT * FROM df")
            
            # Commit transaction
            self.conn.execute("COMMIT")
            print(f"Successfully inserted {len(df)} rows")
            
        except Exception as e:
            self.conn.execute("ROLLBACK")
            print(f"Error inserting data: {str(e)}")
            raise