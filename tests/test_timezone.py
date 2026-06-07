"""Tests for UTC timestamp normalization and TIMESTAMPTZ storage (R5)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import duckdb
import polars as pl

from energex.data_fetcher import normalize_datetime_to_utc
from energex.database import EnergyDatabase


def _dtype(conn) -> str:
    return conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'intraday_prices' AND column_name = 'Datetime'"
    ).fetchone()[0]


def test_datetime_column_is_timestamptz(tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    dtype = _dtype(db.conn)
    db.conn.close()
    assert "TIME ZONE" in dtype  # TIMESTAMP WITH TIME ZONE


def test_stores_utc_instant_from_tz_aware_bar(tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    # 09:30 America/New_York == 14:30 UTC
    df = pl.DataFrame(
        {
            "Datetime": [datetime(2024, 1, 2, 9, 30, tzinfo=ZoneInfo("America/New_York"))],
            "Symbol": ["CL=F"],
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Volume": [1],
        }
    )
    db.insert_intraday_data(df)
    stored = db.conn.execute("SELECT Datetime FROM intraday_prices").fetchone()[0]
    db.conn.close()
    assert stored == datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def test_migrates_legacy_timestamp_column_to_timestamptz(tmp_db_path):
    # Simulate a pre-R5 database with a naive TIMESTAMP column.
    con = duckdb.connect(tmp_db_path)
    con.execute(
        """
        CREATE TABLE intraday_prices (
            Datetime TIMESTAMP, Symbol VARCHAR, Open DOUBLE, High DOUBLE,
            Low DOUBLE, Close DOUBLE, Volume BIGINT,
            CONSTRAINT pk_intraday PRIMARY KEY (Symbol, Datetime)
        )
        """
    )
    con.execute(
        "INSERT INTO intraday_prices VALUES (TIMESTAMP '2024-01-02 14:30:00', 'CL=F', 1, 1, 1, 1, 1)"
    )
    con.close()

    db = EnergyDatabase(tmp_db_path)  # opening must migrate the column type
    dtype = _dtype(db.conn)
    count = db.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    stored = db.conn.execute("SELECT Datetime FROM intraday_prices").fetchone()[0]
    db.conn.close()

    assert "TIME ZONE" in dtype
    assert count == 1
    assert stored == datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def test_normalize_datetime_to_utc_converts_tz_aware():
    df = pl.DataFrame(
        {
            "Datetime": [datetime(2024, 1, 2, 9, 30, tzinfo=ZoneInfo("America/New_York"))],
            "Symbol": ["CL=F"],
        }
    )
    out = normalize_datetime_to_utc(df)
    assert out["Datetime"][0] == datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)


def test_normalize_datetime_to_utc_handles_empty():
    empty = pl.DataFrame()
    assert normalize_datetime_to_utc(empty).is_empty()
