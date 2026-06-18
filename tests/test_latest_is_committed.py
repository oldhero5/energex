"""GATE: an orphan data write (no index entry) is never returned by read_as_of(as_of=None)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
A1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)


def test_latest_is_committed(arctic_lib):
    storage.commit_vintage(
        arctic_lib,
        "CL_CLF26",
        pd.DataFrame({"instrument_id": "CME.CL.CLF26", "valid_time": [D1], "Close": [10.0]}),
        as_of=A1,
        source="yf",
        source_url="u",
        fetched_at=A1,
        mode="bitemporal_merge",
    )
    # Simulate a crash AFTER the data write but BEFORE the index append: a higher,
    # uncommitted data version exists (NOT in {symbol}__vintages).
    orphan = arctic_lib.write(
        "CL_CLF26",
        pd.DataFrame(
            {"Close": [999.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-01")], name="Datetime"),
        ),
        validate_index=True,
    ).version
    assert orphan > 0

    latest = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=None)
    assert float(latest["Close"].iloc[0]) == 10.0  # committed, never the orphan 999.0
