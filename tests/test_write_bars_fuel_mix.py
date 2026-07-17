"""GATE: degenerate write_bars must key dedup on (valid_time, fuel_type) when a
``fuel_type`` column is present (EIA-930 generation-by-fuel emits ~10 rows per hour
distinguished only by fuel), so the full fuel mix survives every write path."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

T1 = datetime(2026, 6, 19, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc)
F = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)

FUELS = ("COL", "NG", "SUN", "WND")


def _fuel_bars(times, fuels=FUELS, base=1000.0):
    rows = []
    for i, t in enumerate(times):
        for j, fuel in enumerate(fuels):
            rows.append(
                {
                    "instrument_id": "EIA930.GEN_FUEL.AECI",
                    "valid_time": t,
                    "respondent": "AECI",
                    "fuel_type": fuel,
                    "value": base + 100.0 * i + j,
                }
            )
    return pd.DataFrame(rows)


def _mix(df):
    """{hour -> set of fuels} as stored."""
    out = {}
    for t, fuel in zip(df.index, df["fuel_type"], strict=True):
        out.setdefault(t.to_pydatetime().replace(tzinfo=timezone.utc), set()).add(fuel)
    return out


def test_multi_fuel_write_preserves_all_fuels(arctic_lib):
    storage.write_bars(arctic_lib, "aeci", _fuel_bars([T1, T2]), fetched_at=F, mode="degenerate")
    out = storage.read_as_of(arctic_lib, "aeci", mode="degenerate")
    assert len(out) == 8  # 4 fuels x 2 hours, nothing collapsed
    assert _mix(out) == {T1: set(FUELS), T2: set(FUELS)}


def test_multi_fuel_rewrite_is_idempotent(arctic_lib):
    v1 = storage.write_bars(
        arctic_lib, "aeci", _fuel_bars([T1, T2]), fetched_at=F, mode="degenerate"
    )
    v2 = storage.write_bars(
        arctic_lib, "aeci", _fuel_bars([T1, T2], base=9999.0), fetched_at=F, mode="degenerate"
    )
    assert v1 == v2  # all (hour, fuel) rows already present => no new version
    out = storage.read_as_of(arctic_lib, "aeci", mode="degenerate")
    assert len(out) == 8
    assert float(out["value"].max()) < 9999.0  # originals untouched


def test_multi_fuel_interior_insert_keeps_neighbors(arctic_lib):
    storage.write_bars(arctic_lib, "aeci", _fuel_bars([T1, T3]), fetched_at=F, mode="degenerate")
    # Re-ingest ONLY the interior hour t2 (sparse insert path).
    storage.write_bars(arctic_lib, "aeci", _fuel_bars([T2]), fetched_at=F, mode="degenerate")
    out = storage.read_as_of(arctic_lib, "aeci", mode="degenerate")
    assert len(out) == 12
    assert _mix(out) == {T1: set(FUELS), T2: set(FUELS), T3: set(FUELS)}
    assert out.index.is_monotonic_increasing  # ArcticDB validate_index contract


def test_multi_fuel_append_after_tail(arctic_lib):
    storage.write_bars(arctic_lib, "aeci", _fuel_bars([T1, T2]), fetched_at=F, mode="degenerate")
    # Strictly after the existing tail => fast-path append.
    storage.write_bars(arctic_lib, "aeci", _fuel_bars([T3]), fetched_at=F, mode="degenerate")
    out = storage.read_as_of(arctic_lib, "aeci", mode="degenerate")
    assert len(out) == 12
    assert _mix(out) == {T1: set(FUELS), T2: set(FUELS), T3: set(FUELS)}


def test_new_fuel_at_existing_hour_is_added(arctic_lib):
    storage.write_bars(
        arctic_lib,
        "aeci",
        _fuel_bars([T1, T2], fuels=("COL", "NG")),
        fetched_at=F,
        mode="degenerate",
    )
    # A fuel not previously reported shows up for an already-stored hour.
    storage.write_bars(
        arctic_lib, "aeci", _fuel_bars([T2], fuels=("SUN",)), fetched_at=F, mode="degenerate"
    )
    out = storage.read_as_of(arctic_lib, "aeci", mode="degenerate")
    assert _mix(out) == {T1: {"COL", "NG"}, T2: {"COL", "NG", "SUN"}}
    assert out.index.is_monotonic_increasing


def test_canonicalize_keeps_fuel_rows_and_sorted_index():
    df = storage._canonicalize(_fuel_bars([T2, T1]), F, "", "", F)
    assert len(df) == 8  # duplicate timestamps across fuels are NOT collapsed
    assert df.index.is_monotonic_increasing
    # True duplicate (same hour AND same fuel) still dedups, keeping the last row.
    dup = pd.concat([_fuel_bars([T1]), _fuel_bars([T1], base=2000.0)], ignore_index=True)
    out = storage._canonicalize(dup, F, "", "", F)
    assert len(out) == 4
    assert set(out["value"]) == {2000.0, 2001.0, 2002.0, 2003.0}
