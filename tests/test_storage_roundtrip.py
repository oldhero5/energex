"""GATE: tz-aware-UTC + dtype (incl. ContractMonth) survive a commit/read/_to_polars round-trip."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import polars as pl

from energex.core import storage


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_id": ["NOAA.HDD.TEXAS", "NOAA.HDD.TEXAS"],
            "valid_time": [
                datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc),
                datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc),
            ],
            "ContractMonth": [date(2024, 1, 1), date(2024, 2, 1)],
            "value": [410.0, 360.0],
        }
    )


def test_storage_roundtrip(arctic_lib):
    as_of = datetime(2024, 2, 5, 16, 0, tzinfo=timezone.utc)
    v = storage.commit_vintage(
        arctic_lib,
        "hdd_texas",
        _frame(),
        as_of=as_of,
        source="noaa-nclimdiv",
        source_url="https://example/noaa",
        fetched_at=as_of,
        mode="bitemporal_replace",
    )
    assert isinstance(v, int)

    vi = arctic_lib.read("hdd_texas", as_of=int(v))
    pf = storage._to_polars(vi)

    # tz preserved as UTC on both time axes.
    assert pf.schema["Datetime"] == pl.Datetime(time_unit="ns", time_zone="UTC")
    assert pf.schema["valid_time"] == pl.Datetime(time_unit="ns", time_zone="UTC")
    # ContractMonth came back as a true date, not datetime64.
    assert pf.schema["ContractMonth"] == pl.Date
    assert pf["ContractMonth"].to_list() == [date(2024, 1, 1), date(2024, 2, 1)]
    assert pf["value"].to_list() == [410.0, 360.0]

    # read_as_of(None) returns the freshly committed vintage as a pandas frame.
    df = storage.read_as_of(arctic_lib, "hdd_texas", as_of=None)
    assert list(df["value"]) == [410.0, 360.0]
    assert df["vintage_reconstructed"].tolist() == [False, False]
