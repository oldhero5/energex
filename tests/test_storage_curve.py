"""read_curve assembles per-contract vintages for a commodity at one as_of."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from energex.core import storage

OBS = datetime(2024, 1, 2, tzinfo=timezone.utc)
AS_OF = datetime(2024, 1, 3, tzinfo=timezone.utc)


def _contract(instrument_id, contract_month, close):
    return pd.DataFrame(
        {
            "instrument_id": [instrument_id],
            "valid_time": [OBS],
            "ContractMonth": [contract_month],
            "Close": [close],
        }
    )


def test_read_curve(arctic_store, arctic_uri, monkeypatch):
    monkeypatch.setenv("ENERGEX_ARCTIC_URI", arctic_uri)
    lib = arctic_store.create_library("prices.futures")
    storage.commit_vintage(
        lib, "CL_CLF26", _contract("CME.CL.CLF26", date(2026, 1, 1), 80.0),
        as_of=AS_OF, source="yf", source_url="u", fetched_at=AS_OF, mode="bitemporal_merge",
    )
    storage.commit_vintage(
        lib, "CL_CLG26", _contract("CME.CL.CLG26", date(2026, 2, 1), 79.5),
        as_of=AS_OF, source="yf", source_url="u", fetched_at=AS_OF, mode="bitemporal_merge",
    )

    curve = storage.read_curve("crude", AS_OF)
    assert sorted(curve["instrument_id"].tolist()) == ["CME.CL.CLF26", "CME.CL.CLG26"]
    assert sorted(curve["Close"].tolist()) == [79.5, 80.0]
