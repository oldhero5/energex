"""GATE: degenerate write_bars is append-with-dedup; re-ingesting an interior bar
must not delete the surrounding bars (no update(date_range))."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

T1 = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
T2 = datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc)
T3 = datetime(2024, 1, 2, 14, 32, tzinfo=timezone.utc)
F = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)


def _bars(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.FRONT", "valid_time": list(times), "Close": list(values)}
    )


def _idx(df):
    return {t.to_pydatetime().replace(tzinfo=timezone.utc) for t in df.index}


def test_write_bars_sparse(arctic_lib):
    storage.write_bars(arctic_lib, "CL_FRONT", _bars([T1, T3], [75.0, 75.2]), fetched_at=F)
    # Re-ingest ONLY the interior bar t2.
    storage.write_bars(arctic_lib, "CL_FRONT", _bars([T2], [75.1]), fetched_at=F)

    out = storage.read_as_of(arctic_lib, "CL_FRONT", as_of=None)
    assert _idx(out) == {T1, T2, T3}  # t1 and t3 survived the sparse interior insert
    assert float(out.loc[out.index == pd.Timestamp("2024-01-02 14:31:00"), "Close"].iloc[0]) == 75.1


def test_write_bars_reingest_is_idempotent(arctic_lib):
    v1 = storage.write_bars(arctic_lib, "CL_FRONT", _bars([T1, T2], [75.0, 75.1]), fetched_at=F)
    v2 = storage.write_bars(arctic_lib, "CL_FRONT", _bars([T1, T2], [99.0, 99.0]), fetched_at=F)
    assert v1 == v2  # all bars already present => no new version, originals untouched
    out = storage.read_as_of(arctic_lib, "CL_FRONT", as_of=None)
    assert float(out.loc[out.index == pd.Timestamp("2024-01-02 14:30:00"), "Close"].iloc[0]) == 75.0
