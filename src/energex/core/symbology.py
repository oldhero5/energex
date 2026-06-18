"""Static symbology for S1: instrument_id <-> (library, symbol, revision_mode).

Numbers live in ArcticDB; this module only routes. The Neo4j graph (phase 9)
references these symbols but never owns them.
"""

from __future__ import annotations

from energex.core.exceptions import SymbologyError

# instrument_id -> (library, symbol, revision_mode)
_TABLE: dict[str, tuple[str, str, str]] = {
    "EIA.NG.STORAGE.LOWER48": ("fundamentals.eia", "ng_storage_lower48", "bitemporal_merge"),
    "EIA.PET.CRUDE.STOCKS": ("fundamentals.eia", "pet_crude_stocks", "bitemporal_merge"),
    "ERCOT.DALMP.HB_HOUSTON": ("prices.power", "dalmp_hb_houston", "bitemporal_merge"),
    # NOAA nClimDiv monthly degree days: one combined HDD+CDD instrument per region
    # (contiguous-US national aggregate, the nine NCEI climate regions, and Texas).
    "NOAA.HDD.CONUS": ("weather", "hdd_conus", "bitemporal_replace"),
    "NOAA.HDD.NORTHEAST": ("weather", "hdd_northeast", "bitemporal_replace"),
    "NOAA.HDD.ENCENTRAL": ("weather", "hdd_encentral", "bitemporal_replace"),
    "NOAA.HDD.CENTRAL": ("weather", "hdd_central", "bitemporal_replace"),
    "NOAA.HDD.SOUTHEAST": ("weather", "hdd_southeast", "bitemporal_replace"),
    "NOAA.HDD.WNCENTRAL": ("weather", "hdd_wncentral", "bitemporal_replace"),
    "NOAA.HDD.SOUTH": ("weather", "hdd_south", "bitemporal_replace"),
    "NOAA.HDD.SOUTHWEST": ("weather", "hdd_southwest", "bitemporal_replace"),
    "NOAA.HDD.NORTHWEST": ("weather", "hdd_northwest", "bitemporal_replace"),
    "NOAA.HDD.WEST": ("weather", "hdd_west", "bitemporal_replace"),
    "NOAA.HDD.TEXAS": ("weather", "hdd_texas", "bitemporal_replace"),
    # FRED daily benchmark spot prices: final daily values (no vintage) -> degenerate.
    "FRED.WTI.SPOT": ("prices.spot", "wti_spot", "degenerate"),
    "FRED.BRENT.SPOT": ("prices.spot", "brent_spot", "degenerate"),
    "FRED.HENRYHUB.SPOT": ("prices.spot", "henryhub_spot", "degenerate"),
    "CME.CL.FRONT": ("prices.intraday", "CL_FRONT", "degenerate"),
    "CME.BZ.FRONT": ("prices.intraday", "BZ_FRONT", "degenerate"),
    "CME.NG.FRONT": ("prices.intraday", "NG_FRONT", "degenerate"),
    "CME.CL.CLF26": ("prices.futures", "CL_CLF26", "bitemporal_merge"),
    "CME.CL.CLG26": ("prices.futures", "CL_CLG26", "bitemporal_merge"),
}

# The single source of truth for which revision mode each library class implies.
LIBRARY_MODE: dict[str, str] = {
    "fundamentals.eia": "bitemporal_merge",
    "prices.power": "bitemporal_merge",
    "weather": "bitemporal_replace",
    "prices.spot": "degenerate",
    "prices.intraday": "degenerate",
    "prices.futures": "bitemporal_merge",
}

# commodity -> ordered list of contract SYMBOL strings (used by read_curve).
_CONTRACTS: dict[str, list[str]] = {
    "crude": ["CL_CLF26", "CL_CLG26"],
}

# Reverse index: symbol -> (library, revision_mode).
_BY_SYMBOL: dict[str, tuple[str, str]] = {
    symbol: (library, mode) for library, symbol, mode in _TABLE.values()
}


def resolve(instrument_id: str) -> tuple[str, str]:
    try:
        library, symbol, _mode = _TABLE[instrument_id]
    except KeyError as exc:
        raise SymbologyError(f"unknown instrument_id {instrument_id!r}") from exc
    return (library, symbol)


def revision_mode(instrument_id: str) -> str:
    try:
        return _TABLE[instrument_id][2]
    except KeyError as exc:
        raise SymbologyError(f"unknown instrument_id {instrument_id!r}") from exc


def contracts_for(commodity: str) -> list[str]:
    try:
        return list(_CONTRACTS[commodity])
    except KeyError as exc:
        raise SymbologyError(f"unknown commodity {commodity!r}") from exc


def mode_for_symbol(symbol: str) -> str:
    try:
        return _BY_SYMBOL[symbol][1]
    except KeyError as exc:
        raise SymbologyError(f"unknown symbol {symbol!r}") from exc


def library_for_symbol(symbol: str) -> str:
    try:
        return _BY_SYMBOL[symbol][0]
    except KeyError as exc:
        raise SymbologyError(f"unknown symbol {symbol!r}") from exc
