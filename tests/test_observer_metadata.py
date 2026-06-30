"""Tests for observer schema_map and metadata.list_catalog()."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from energex.core import schemas
from energex.observer import schema_map


def test_schema_for_maps_known_libraries():
    assert schema_map.schema_for("power.load", "erco") is schemas.ERCOT_LOAD
    assert schema_map.schema_for("prices.spot", "wti_spot") is schemas.FRED_SPOT
    # fundamentals.eia splits by symbol
    assert (
        schema_map.schema_for("fundamentals.eia", "ng_storage_lower48") is schemas.EIA_GAS_STORAGE
    )
    assert schema_map.schema_for("fundamentals.eia", "pet_crude_stocks") is schemas.EIA_PETROLEUM
    assert schema_map.schema_for("totally.unknown", "x") is None


def _seed_bitemporal(lib, symbol="erco"):
    from energex.core import storage

    base = pd.DataFrame(
        {
            "instrument_id": ["ERCOT.LOAD"],
            "valid_time": [pd.Timestamp("2026-06-01", tz="UTC")],
            "value": [40000.0],
        }
    ).set_index(pd.DatetimeIndex([pd.Timestamp("2026-06-01")], name="Datetime"))
    storage.commit_vintage(
        lib,
        symbol,
        base,
        as_of=dt.datetime(2026, 6, 2, tzinfo=dt.timezone.utc),
        source="ercot",
        source_url="x",
        fetched_at=dt.datetime(2026, 6, 2, tzinfo=dt.timezone.utc),
        mode="bitemporal_merge",
    )


def test_list_catalog_reports_cheap_metadata(observer_arctic):  # fixture creates lib 'power.load'
    lib = observer_arctic["power.load"]
    _seed_bitemporal(lib)
    from energex.observer import metadata

    cat = metadata.list_catalog()
    powerload = next(lib for lib in cat["libraries"] if lib["name"] == "power.load")
    assert powerload["mode"] == "bitemporal_merge"
    sym = next(s for s in powerload["symbols"] if s["symbol"] == "erco")
    assert sym["row_count"] == 1
    assert sym["vintage_count"] == 1
    assert sym["schema_name"] == "ERCOT_LOAD"
    # the __vintages sidecar symbol must be excluded from the symbol list
    assert all(not s["symbol"].endswith("__vintages") for s in powerload["symbols"])
