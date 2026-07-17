"""Public vocabulary accessors the entity graph consumes (never private dicts)."""

from energex.core import symbology
from energex.core.connectors import ercot
from energex.core.exceptions import EnergexError, GraphError


def test_symbology_instruments_enumerates_static_table():
    ids = symbology.instruments()
    assert "EIA.NG.STORAGE.LOWER48" in ids
    assert "FRED.WTI.SPOT" in ids
    assert "NOAA.HDD.TEXAS" in ids
    # rule-based power ids are NOT in the static universe
    assert not any(i.startswith("EIA930.") for i in ids)
    # accessor returns a copy: mutating it must not corrupt the table
    ids.clear()
    assert symbology.instruments()


def test_symbology_power_prefixes_maps_prefix_to_library_and_mode():
    prefixes = symbology.power_prefixes()
    assert prefixes["EIA930.D"] == ("power.demand", "degenerate")
    assert prefixes["ERCOT.SPP"] == ("power.lmp", "bitemporal_merge")
    prefixes.clear()
    assert symbology.power_prefixes()


def test_ercot_settlement_points_public_accessor():
    points = ercot.settlement_points()
    assert "HB_NORTH" in points and "LZ_HOUSTON" in points
    assert len(points) == 13


def test_graph_error_is_energex_error():
    assert issubclass(GraphError, EnergexError)
