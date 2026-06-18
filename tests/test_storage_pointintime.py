"""GATE: a later release revises an earlier period; each as_of reads its own truth."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
D3 = datetime(2024, 1, 15, tzinfo=timezone.utc)
A1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)
A2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)


def _frame(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.CLF26", "valid_time": list(times), "Close": list(values)}
    )


def _close_at(df, when):
    naive = pd.Timestamp(when).tz_convert("UTC").tz_localize(None)
    return float(df.loc[df.index == naive, "Close"].iloc[0])


def test_pointintime_two_vintage(arctic_lib):
    storage.commit_vintage(
        arctic_lib,
        "CL_CLF26",
        _frame([D1, D2, D3], [10.0, 11.0, 12.0]),
        as_of=A1,
        source="yf",
        source_url="u",
        fetched_at=A1,
        mode="bitemporal_merge",
    )
    # A2 revises only the [D2, D3] lookback window.
    storage.commit_vintage(
        arctic_lib,
        "CL_CLF26",
        _frame([D2, D3], [21.0, 22.0]),
        as_of=A2,
        source="yf",
        source_url="u",
        fetched_at=A2,
        mode="bitemporal_merge",
    )

    pre = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=A1)
    post = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=A2)

    assert _close_at(pre, D2) == 11.0 and _close_at(pre, D3) == 12.0  # pre-revision
    assert _close_at(post, D2) == 21.0 and _close_at(post, D3) == 22.0  # revised
    assert _close_at(post, D1) == 10.0  # untouched earlier row preserved


def test_idempotent_recommit_is_a_noop(arctic_lib):
    v1 = storage.commit_vintage(
        arctic_lib,
        "CL_CLF26",
        _frame([D1, D2], [10.0, 11.0]),
        as_of=A1,
        source="yf",
        source_url="u",
        fetched_at=A1,
        mode="bitemporal_merge",
    )
    v2 = storage.commit_vintage(
        arctic_lib,
        "CL_CLF26",
        _frame([D1, D2], [99.0, 99.0]),
        as_of=A1,
        source="yf",
        source_url="u",
        fetched_at=A1,
        mode="bitemporal_merge",
    )
    assert v1 == v2  # same as_of => no new version, original values intact
    assert _close_at(storage.read_as_of(arctic_lib, "CL_CLF26", as_of=A1), D1) == 10.0
