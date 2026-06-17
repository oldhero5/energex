"""GATE: a revision frame with an interior gap must NOT delete the omitted prior row."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
D3 = datetime(2024, 1, 15, tzinfo=timezone.utc)
B1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)
B2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)


def _frame(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.CLF26", "valid_time": list(times), "Close": list(values)}
    )


def test_revision_merge_gap(arctic_lib):
    storage.commit_vintage(
        arctic_lib,
        "CL_CLF26",
        _frame([D1, D2, D3], [10.0, 11.0, 12.0]),
        as_of=B1,
        source="yf",
        source_url="u",
        fetched_at=B1,
        mode="bitemporal_merge",
    )
    # B2 revises D1 and D3 but OMITS D2 (a gap inside the revised span).
    storage.commit_vintage(
        arctic_lib,
        "CL_CLF26",
        _frame([D1, D3], [100.0, 300.0]),
        as_of=B2,
        source="yf",
        source_url="u",
        fetched_at=B2,
        mode="bitemporal_merge",
    )

    post = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=B2)

    def at(d):
        naive = pd.Timestamp(d).tz_convert("UTC").tz_localize(None)
        return float(post.loc[post.index == naive, "Close"].iloc[0])

    assert at(D1) == 100.0  # revised
    assert at(D3) == 300.0  # revised
    assert at(D2) == 11.0  # OMITTED row preserved, NOT deleted
