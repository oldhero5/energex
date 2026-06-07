"""Tests for EnergyDatabase persistence: no data loss + idempotent upsert (R1+R2)."""

from datetime import datetime

import polars as pl
import pytest

from energex.database import EnergyDatabase
from energex.exceptions import DatabaseError


def test_history_survives_reinstantiation(sample_ohlcv, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_intraday_data(sample_ohlcv)
    db.conn.close()

    # Re-opening the database must NOT drop existing history.
    db2 = EnergyDatabase(tmp_db_path)
    count = db2.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    db2.conn.close()
    assert count == sample_ohlcv.height


def test_reinserting_same_batch_does_not_duplicate(sample_ohlcv, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_intraday_data(sample_ohlcv)
    db.insert_intraday_data(sample_ohlcv)  # overlapping/duplicate window
    count = db.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    db.conn.close()
    assert count == sample_ohlcv.height


def test_overlapping_batch_updates_changed_values(sample_ohlcv, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_intraday_data(sample_ohlcv)

    revised = sample_ohlcv.with_columns((pl.col("Close") + 1.0).alias("Close"))
    db.insert_intraday_data(revised)

    count = db.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    first_close = db.conn.execute(
        "SELECT Close FROM intraday_prices WHERE Symbol = 'CL=F' ORDER BY Datetime LIMIT 1"
    ).fetchone()[0]
    db.conn.close()

    expected = revised.filter(pl.col("Symbol") == "CL=F").sort("Datetime")["Close"][0]
    assert count == sample_ohlcv.height  # no new rows, just updates
    assert first_close == pytest.approx(expected)


def test_read_only_mode_does_not_mutate_and_rejects_writes(sample_ohlcv, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_intraday_data(sample_ohlcv)
    db.conn.close()

    ro = EnergyDatabase(tmp_db_path, read_only=True)
    count = ro.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    assert count == sample_ohlcv.height
    with pytest.raises(Exception):  # noqa: B017 - duckdb raises on write to a read-only conn
        ro.conn.execute("INSERT INTO intraday_prices VALUES (NULL, 'X', 1, 1, 1, 1, 1)")
    ro.conn.close()


def test_reset_clears_existing_data(sample_ohlcv, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_intraday_data(sample_ohlcv)
    db.reset()
    count = db.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    db.conn.close()
    assert count == 0


def test_read_only_reset_is_rejected(sample_ohlcv, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_intraday_data(sample_ohlcv)
    db.conn.close()
    ro = EnergyDatabase(tmp_db_path, read_only=True)
    with pytest.raises(DatabaseError):
        ro.reset()
    ro.conn.close()


def test_insert_rejects_frame_missing_required_columns(tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    bad = pl.DataFrame({"Datetime": [datetime(2024, 1, 1)], "Symbol": ["CL=F"]})
    with pytest.raises(DatabaseError):
        db.insert_intraday_data(bad)
    db.conn.close()


def test_column_order_does_not_corrupt_ohlc(tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    # Columns provided in a scrambled order must still land in the right columns.
    scrambled = pl.DataFrame(
        {
            "Volume": [1000],
            "Close": [75.5],
            "Symbol": ["CL=F"],
            "Low": [74.0],
            "Datetime": [datetime(2024, 1, 2, 14, 30)],
            "High": [76.0],
            "Open": [75.0],
        }
    )
    db.insert_intraday_data(scrambled)
    row = db.conn.execute("SELECT Open, High, Low, Close, Volume FROM intraday_prices").fetchone()
    db.conn.close()
    assert row == (75.0, 76.0, 74.0, 75.5, 1000)
