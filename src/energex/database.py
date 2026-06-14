# src/energex/database.py
import logging
from pathlib import Path
from types import TracebackType
from typing import Any

import duckdb
import polars as pl

from energex.config import get_settings
from energex.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class EnergyDatabase:
    """DuckDB-backed store for intraday OHLCV bars.

    Ingestion is idempotent: rows are upserted on the ``(Symbol, Datetime)``
    primary key so re-running a fetch (or an overlapping window) accumulates and
    corrects history instead of destroying it.
    """

    #: Canonical column order for the ``intraday_prices`` table.
    COLUMNS = ("Datetime", "Symbol", "Open", "High", "Low", "Close", "Volume")

    #: Canonical column order for the ``daily_contracts`` table (dated contract strip).
    DAILY_CONTRACTS_COLUMNS = (
        "Datetime",
        "Commodity",
        "ContractMonth",
        "Symbol",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "OpenInterest",
    )

    def __init__(self, db_path: str | None = None, read_only: bool = False):
        # Resolve the path from configuration (ENERGEX_DB_PATH) when not given.
        if db_path is None:
            db_path = str(get_settings().database.db_path)
        self.db_path = Path(db_path)
        self.read_only = read_only
        self._closed = False
        if read_only and not self.db_path.exists():
            raise DatabaseError(
                f"Cannot open database read-only; file does not exist: {self.db_path}"
            )
        self.conn = duckdb.connect(str(self.db_path), read_only=read_only)
        # Store and display timestamps as UTC instants regardless of the host timezone.
        self.conn.execute("SET TimeZone = 'UTC'")
        # Schema creation is DDL and cannot run on a read-only connection; callers
        # that only inspect/read (e.g. `main --check`) pass read_only=True.
        if not read_only:
            self._init_tables()
            self._migrate_to_timestamptz()

    def _init_tables(self) -> None:
        """Create the storage tables if they do not already exist (idempotent)."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS intraday_prices (
                Datetime TIMESTAMPTZ,
                Symbol VARCHAR,
                Open DOUBLE,
                High DOUBLE,
                Low DOUBLE,
                Close DOUBLE,
                Volume BIGINT,
                CONSTRAINT pk_intraday PRIMARY KEY (Symbol, Datetime)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_contracts (
                Datetime TIMESTAMPTZ,
                Commodity VARCHAR,
                ContractMonth DATE,
                Symbol VARCHAR,
                Open DOUBLE,
                High DOUBLE,
                Low DOUBLE,
                Close DOUBLE,
                Volume BIGINT,
                OpenInterest BIGINT,
                CONSTRAINT pk_daily_contracts PRIMARY KEY (Commodity, ContractMonth, Datetime)
            )
        """)

    def _migrate_to_timestamptz(self) -> None:
        """Migrate a legacy naive-TIMESTAMP Datetime column to TIMESTAMPTZ (UTC).

        Pre-R5 databases stored Datetime as a host-tz-dependent naive TIMESTAMP. Treat
        those existing values as UTC and recreate-and-swap into a TIMESTAMPTZ column.
        """
        row = self.conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'intraday_prices' AND column_name = 'Datetime'"
        ).fetchone()
        if not row or "TIME ZONE" in row[0]:
            return  # already TIMESTAMPTZ (or no table)

        self.conn.execute("BEGIN TRANSACTION")
        try:
            self.conn.execute("""
                CREATE TABLE intraday_prices_tz (
                    Datetime TIMESTAMPTZ,
                    Symbol VARCHAR,
                    Open DOUBLE,
                    High DOUBLE,
                    Low DOUBLE,
                    Close DOUBLE,
                    Volume BIGINT,
                    CONSTRAINT pk_intraday PRIMARY KEY (Symbol, Datetime)
                )
            """)
            self.conn.execute("""
                INSERT INTO intraday_prices_tz
                SELECT Datetime AT TIME ZONE 'UTC', Symbol, Open, High, Low, Close, Volume
                FROM intraday_prices
            """)
            self.conn.execute("DROP TABLE intraday_prices")
            self.conn.execute("ALTER TABLE intraday_prices_tz RENAME TO intraday_prices")
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def reset(self) -> None:
        """Drop and recreate the tables. Destructive — for explicit bootstrap only."""
        if self.read_only:
            raise DatabaseError("Cannot reset a read-only database connection")
        self.conn.execute("DROP TABLE IF EXISTS intraday_prices")
        self.conn.execute("DROP TABLE IF EXISTS daily_contracts")
        self._init_tables()

    def insert_intraday_data(self, df: pl.DataFrame) -> None:
        """Idempotently upsert intraday OHLCV rows keyed by (Symbol, Datetime)."""
        if df.is_empty():
            logger.info("No data to insert")
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
            logger.info("Upserted %d rows", len(df))
        except Exception as e:
            self.conn.execute("ROLLBACK")
            logger.error("Error inserting data: %s", e)
            raise

    def insert_daily_contracts(self, df: pl.DataFrame) -> None:
        """Idempotently upsert dated-contract daily bars keyed by
        (Commodity, ContractMonth, Datetime)."""
        if df.is_empty():
            logger.info("No daily contracts to insert")
            return

        missing = [c for c in self.DAILY_CONTRACTS_COLUMNS if c not in df.columns]
        if missing:
            raise DatabaseError(
                f"DataFrame is missing required columns {missing}; got {df.columns}"
            )

        # Select named columns in canonical order so the INSERT never binds positionally.
        df = df.select(self.DAILY_CONTRACTS_COLUMNS)

        try:
            self.conn.execute("BEGIN TRANSACTION")
            self.conn.execute("""
                INSERT INTO daily_contracts
                    (Datetime, Commodity, ContractMonth, Symbol,
                     Open, High, Low, Close, Volume, OpenInterest)
                SELECT Datetime, Commodity, ContractMonth, Symbol,
                       Open, High, Low, Close, Volume, OpenInterest FROM df
                ON CONFLICT (Commodity, ContractMonth, Datetime) DO UPDATE SET
                    Symbol = excluded.Symbol,
                    Open = excluded.Open,
                    High = excluded.High,
                    Low = excluded.Low,
                    Close = excluded.Close,
                    Volume = excluded.Volume,
                    OpenInterest = excluded.OpenInterest
            """)
            self.conn.execute("COMMIT")
            logger.info("Upserted %d daily contract rows", len(df))
        except Exception as e:
            self.conn.execute("ROLLBACK")
            logger.error("Error inserting daily contracts: %s", e)
            raise

    def query(self, sql: str, params: list[Any] | None = None) -> pl.DataFrame:
        """Run a read query on a separate cursor and return a Polars DataFrame."""
        result = pl.from_arrow(self.conn.cursor().execute(sql, params or []).arrow())
        assert isinstance(result, pl.DataFrame)
        return result

    def close(self) -> None:
        """Close the underlying DuckDB connection (idempotent)."""
        if not self._closed:
            self.conn.close()
            self._closed = True

    def __enter__(self) -> "EnergyDatabase":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
