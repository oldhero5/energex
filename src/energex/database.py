import duckdb
import polars as pl
from pathlib import Path

class EnergyDatabase:
    def __init__(self, db_path: str = "energy.db"):
        self.db_path = Path(db_path)
        self.conn = duckdb.connect(str(self.db_path))
        self._init_tables()
    
    def _init_tables(self):
        """Initialize database tables if they don't exist."""
        # Drop existing tables if they exist
        self.conn.execute("DROP TABLE IF EXISTS securities")
        self.conn.execute("DROP TABLE IF EXISTS options")
        
        # Create securities table with consistent schema
        self.conn.execute("""
            CREATE TABLE securities (
                symbol VARCHAR,
                date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                adj_close DOUBLE,
                type VARCHAR,
                description VARCHAR
            )
        """)
        
        # Create index on commonly queried columns
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_securities_symbol_date 
            ON securities(symbol, date)
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS securities (
                symbol VARCHAR,
                date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                adj_close DOUBLE,
                type VARCHAR,
                description VARCHAR
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS options (
                symbol VARCHAR,
                date TIMESTAMP,
                expiration TIMESTAMP,
                strike DOUBLE,
                option_type VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                open_interest BIGINT
            )
        """)
    
    def insert_securities_data(self, df: pl.DataFrame, security_type: str, description: str):
        """Insert securities data into the database."""
        print(f"Input DataFrame columns: {df.columns}")
        
        # Ensure DataFrame columns match the table schema
        df = (df.with_columns([
            pl.col("volume").cast(pl.Int64),
            pl.lit(security_type).alias("type"),
            pl.lit(description).alias("description")
        ]))
        
        # Ensure columns are in the correct order
        expected_columns = ["symbol", "date", "open", "high", "low", "close", 
                          "volume", "adj_close", "type", "description"]
        df = df.select(expected_columns)
        
        print(f"Final DataFrame schema:")
        print(df.schema)
        
        # Create DuckDB table from Polars DataFrame
        try:
            self.conn.execute("INSERT INTO securities SELECT * FROM df")
            self.conn.commit()
            print(f"Successfully inserted {len(df)} rows")
        except Exception as e:
            print(f"Error inserting data: {e}")
            raise
