"""Tests for daily_contracts storage: idempotent upsert + PK integrity."""

from datetime import date, datetime, timezone

import polars as pl
import pytest

from energex.database import EnergyDatabase
from energex.exceptions import DatabaseError


def test_history_survives_reinstantiation(sample_daily_contracts, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_daily_contracts(sample_daily_contracts)
    db.conn.close()

    db2 = EnergyDatabase(tmp_db_path)
    count = db2.conn.execute("SELECT COUNT(*) FROM daily_contracts").fetchone()[0]
    db2.conn.close()
    assert count == sample_daily_contracts.height


def test_reinserting_same_batch_does_not_duplicate(sample_daily_contracts, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_daily_contracts(sample_daily_contracts)
    db.insert_daily_contracts(sample_daily_contracts)
    count = db.conn.execute("SELECT COUNT(*) FROM daily_contracts").fetchone()[0]
    db.conn.close()
    assert count == sample_daily_contracts.height


def test_upsert_updates_close_on_conflict(sample_daily_contracts, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_daily_contracts(sample_daily_contracts)

    revised = sample_daily_contracts.with_columns((pl.col("Close") + 1.0).alias("Close"))
    db.insert_daily_contracts(revised)

    count = db.conn.execute("SELECT COUNT(*) FROM daily_contracts").fetchone()[0]
    first = db.conn.execute(
        "SELECT Close FROM daily_contracts "
        "WHERE Commodity = 'crude' ORDER BY ContractMonth, Datetime LIMIT 1"
    ).fetchone()[0]
    db.conn.close()

    expected = revised.filter(pl.col("Commodity") == "crude").sort(["ContractMonth", "Datetime"])[
        "Close"
    ][0]
    assert count == sample_daily_contracts.height
    assert first == pytest.approx(expected)


def test_read_only_mode_rejects_writes(sample_daily_contracts, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_daily_contracts(sample_daily_contracts)
    db.conn.close()

    ro = EnergyDatabase(tmp_db_path, read_only=True)
    count = ro.conn.execute("SELECT COUNT(*) FROM daily_contracts").fetchone()[0]
    assert count == sample_daily_contracts.height
    with pytest.raises(Exception):  # noqa: B017 - duckdb raises on write to a read-only conn
        ro.conn.execute(
            "INSERT INTO daily_contracts VALUES "
            "(NULL, 'x', DATE '2024-02-01', 'X', 1, 1, 1, 1, 1, 1)"
        )
    ro.conn.close()


def test_reset_clears_daily_contracts(sample_daily_contracts, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_daily_contracts(sample_daily_contracts)
    db.reset()
    count = db.conn.execute("SELECT COUNT(*) FROM daily_contracts").fetchone()[0]
    db.conn.close()
    assert count == 0


def test_insert_rejects_frame_missing_required_columns(tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    bad = pl.DataFrame(
        {
            "Datetime": [datetime(2024, 1, 2, tzinfo=timezone.utc)],
            "Commodity": ["crude"],
            "ContractMonth": [date(2024, 2, 1)],
        }
    )
    with pytest.raises(DatabaseError):
        db.insert_daily_contracts(bad)
    db.conn.close()


def test_primary_key_is_commodity_month_datetime(sample_daily_contracts, tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.insert_daily_contracts(sample_daily_contracts)
    # Same (Commodity, ContractMonth, Datetime) but different Symbol must upsert, not add.
    dup = sample_daily_contracts.head(1).with_columns(pl.lit("OTHER.NYM").alias("Symbol"))
    db.insert_daily_contracts(dup)
    count = db.conn.execute("SELECT COUNT(*) FROM daily_contracts").fetchone()[0]
    sym = db.conn.execute(
        "SELECT Symbol FROM daily_contracts WHERE Commodity = ? AND ContractMonth = ? "
        "AND Datetime = ?",
        [
            dup["Commodity"][0],
            dup["ContractMonth"][0],
            dup["Datetime"][0],
        ],
    ).fetchone()[0]
    db.conn.close()
    assert count == sample_daily_contracts.height
    assert sym == "OTHER.NYM"
