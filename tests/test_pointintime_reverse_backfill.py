"""GATE: writing vintages in REVERSE as_of order must not leak later knowledge backward."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from energex.core import storage

D1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
D2 = datetime(2024, 1, 8, tzinfo=timezone.utc)
D3 = datetime(2024, 1, 15, tzinfo=timezone.utc)
D4 = datetime(2024, 1, 22, tzinfo=timezone.utc)  # only known at the LATER as_of
A1 = datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)  # earlier
A2 = datetime(2024, 1, 23, 15, 30, tzinfo=timezone.utc)  # later


def _frame(times, values):
    return pd.DataFrame(
        {"instrument_id": "CME.CL.CLF26", "valid_time": list(times), "Close": list(values)}
    )


def test_pointintime_reverse_backfill(arctic_lib):
    # Commit the LATER vintage first (carries the extra D4 row).
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D2, D3, D4], [21.0, 22.0, 40.0]),
        as_of=A2, source="yf", source_url="u", fetched_at=A2, mode="bitemporal_merge",
    )
    # Then backfill the EARLIER vintage (no D4).
    storage.commit_vintage(
        arctic_lib, "CL_CLF26", _frame([D1, D2, D3], [10.0, 11.0, 12.0]),
        as_of=A1, source="yf", source_url="u", fetched_at=A1, mode="bitemporal_merge",
    )

    early = storage.read_as_of(arctic_lib, "CL_CLF26", as_of=A1)
    early_naive = {pd.Timestamp(t).tz_convert("UTC").tz_localize(None) for t in (D1, D2, D3)}
    assert set(early.index) == early_naive  # NO D4 leak from the later vintage

    # as_of strictly before the earliest committed vintage => EMPTY.
    before = datetime(2023, 12, 31, tzinfo=timezone.utc)
    assert storage.read_as_of(arctic_lib, "CL_CLF26", as_of=before).empty
