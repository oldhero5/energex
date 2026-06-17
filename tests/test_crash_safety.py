"""GATE: a kill between data-write and index-append leaves a GC-able orphan;
read_as_of still returns the prior committed vintage (never an older one)."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
E1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)
E2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)


def _frame(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.CLF26", "valid_time": list(times), "Close": list(values)}
    )


def _versions(lib, symbol):
    return {k.version for k in lib.list_versions(symbol) if k.symbol == symbol}


def test_crash_safety(arctic_lib):
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1], [10.0]),
        as_of=E1, source="yf", source_url="u", fetched_at=E1, mode="bitemporal_merge",
    )
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D2], [10.0, 11.0]),
        as_of=E2, source="yf", source_url="u", fetched_at=E2, mode="bitemporal_merge",
    )

    # CRASH: data version written, index append never happened.
    orphan = arctic_lib.write(
        "CL_CLF26",
        pd.DataFrame({"Close": [999.0]},
                     index=pd.DatetimeIndex([pd.Timestamp("2024-01-01")], name="Datetime")),
        validate_index=True,
    ).version

    committed = {e.version for e in storage._read_vintage_index(arctic_lib, "CL_CLF26")}
    assert orphan in _versions(arctic_lib, "CL_CLF26") and orphan not in committed

    # read_as_of returns the prior committed vintage (E2), not the orphan, not E1.
    latest = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=None)
    assert float(latest.loc[latest.index == pd.Timestamp("2024-01-08"), "Close"].iloc[0]) == 11.0

    # GC removes the orphan; committed reads are unaffected.
    removed = storage.reconcile_orphans(arctic_lib, "CL_CLF26")
    assert removed == [orphan]
    assert orphan not in _versions(arctic_lib, "CL_CLF26")
    latest2 = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=None)
    assert float(latest2.loc[latest2.index == pd.Timestamp("2024-01-08"), "Close"].iloc[0]) == 11.0
