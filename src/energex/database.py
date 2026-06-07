# src/energex/database.py
from pathlib import Path

import duckdb
import polars as pl

from energex.exceptions import DatabaseError


class EnergyDatabase:
    """DuckDB-backed store for intraday OHLCV bars.

    Ingestion is idempotent: rows are upserted on the ``(Symbol, Datetime)``
    primary key so re-running a fetch (or an overlapping window) accumulates and
    corrects history instead of destroying it.
    """

    #: Canonical column order for the ``intraday_prices`` table.
    COLUMNS = ("Datetime", "Symbol", "Open", "High", "Low", "Close", "Volume")

    def __init__(self, db_path: str = "energy.db", read_only: bool = False):
        self.db_path = Path(db_path)
        self.read_only = read_only
        if read_only and not self.db_path.exists():
            raise DatabaseError(
                f"Cannot open database read-only; file does not exist: {self.db_path}"
            )
        self.conn = duckdb.connect(str(self.db_path), read_only=read_only)
        # Schema creation is DDL and cannot run on a read-only connection; callers
        # that only inspect/read (e.g. `main --check`) pass read_only=True.
        if not read_only:
            self._init_tables()

    def _init_tables(self) -> None:
        """Create the intraday_prices table if it does not already exist (idempotent)."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS intraday_prices (
                Datetime TIMESTAMP,
                Symbol VARCHAR,
                Open DOUBLE,
                High DOUBLE,
                Low DOUBLE,
                Close DOUBLE,
                Volume BIGINT,
                CONSTRAINT pk_intraday PRIMARY KEY (Symbol, Datetime)
            )
        """)

    def reset(self) -> None:
        """Drop and recreate the table. Destructive — for explicit bootstrap only."""
        if self.read_only:
            raise DatabaseError("Cannot reset a read-only database connection")
        self.conn.execute("DROP TABLE IF EXISTS intraday_prices")
        self._init_tables()

    def insert_intraday_data(self, df: pl.DataFrame) -> None:
        """Idempotently upsert intraday OHLCV rows keyed by (Symbol, Datetime)."""
        if df.is_empty():
            print("No data to insert")
            return

        missing = [c for c in self.COLUMNS if c not in df.columns]
        if missing:
            raise DatabaseError(
                f"DataFrame is missing required columns {missing}; got {df.columns}"
            )

        # Select named columns in canonical order so the INSERT never binds
        # positionally (a column-order change must not silently swap OHLC values).
        df = df.select(self.COLUMNS)

        try:
            self.conn.execute("BEGIN TRANSACTION")
            self.conn.execute("""
                INSERT INTO intraday_prices
                    (Datetime, Symbol, Open, High, Low, Close, Volume)
                SELECT Datetime, Symbol, Open, High, Low, Close, Volume FROM df
                ON CONFLICT (Symbol, Datetime) DO UPDATE SET
                    Open = excluded.Open,
                    High = excluded.High,
                    Low = excluded.Low,
                    Close = excluded.Close,
                    Volume = excluded.Volume
            """)
            self.conn.execute("COMMIT")
            print(f"Upserted {len(df)} rows")
        except Exception as e:
            self.conn.execute("ROLLBACK")
            print(f"Error inserting data: {e}")
            raise
