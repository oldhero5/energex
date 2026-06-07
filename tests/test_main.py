"""Tests for the CLI helpers in energex.main (R1: read-only --check, explicit reset)."""

from energex import main as main_module


def test_check_schema_is_read_only_and_preserves_data(sample_ohlcv, tmp_db_path):
    from energex.database import EnergyDatabase

    db = EnergyDatabase(tmp_db_path)
    db.insert_intraday_data(sample_ohlcv)
    db.conn.close()

    schema = main_module.check_schema(tmp_db_path)
    columns = {row[0] for row in schema}
    assert {"Datetime", "Symbol", "Open", "High", "Low", "Close", "Volume"} <= columns

    # Inspection must not have mutated the data.
    db2 = EnergyDatabase(tmp_db_path)
    count = db2.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    db2.conn.close()
    assert count == sample_ohlcv.height


def test_reset_database_clears_rows(sample_ohlcv, tmp_db_path):
    from energex.database import EnergyDatabase

    db = EnergyDatabase(tmp_db_path)
    db.insert_intraday_data(sample_ohlcv)
    db.conn.close()

    main_module.reset_database(tmp_db_path)

    db2 = EnergyDatabase(tmp_db_path)
    count = db2.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    db2.conn.close()
    assert count == 0
