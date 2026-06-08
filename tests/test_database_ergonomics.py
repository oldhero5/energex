"""Tests for EnergyDatabase ergonomics: context manager, query helper, db_path (R15)."""

import polars as pl
import pytest

from energex.config import reset_settings
from energex.database import EnergyDatabase


def test_context_manager_closes_connection(sample_ohlcv, tmp_db_path):
    with EnergyDatabase(tmp_db_path) as db:
        db.insert_intraday_data(sample_ohlcv)
    # After the block the connection is closed.
    with pytest.raises(Exception):  # noqa: B017 - duckdb raises on a closed connection
        db.conn.execute("SELECT 1")


def test_close_is_idempotent(tmp_db_path):
    db = EnergyDatabase(tmp_db_path)
    db.close()
    db.close()  # must not raise


def test_query_returns_dataframe(sample_ohlcv, tmp_db_path):
    with EnergyDatabase(tmp_db_path) as db:
        db.insert_intraday_data(sample_ohlcv)
        out = db.query("SELECT * FROM intraday_prices WHERE Symbol = ? ORDER BY Datetime", ["CL=F"])
    assert isinstance(out, pl.DataFrame)
    assert set(out["Symbol"].unique()) == {"CL=F"}


def test_db_path_none_resolves_from_settings(monkeypatch, tmp_path):
    target = tmp_path / "configured.db"
    monkeypatch.setenv("ENERGEX_DB_PATH", str(target))
    reset_settings()
    try:
        db = EnergyDatabase()  # None -> settings.database.db_path
        assert str(db.db_path) == str(target)
        db.close()
    finally:
        reset_settings()
