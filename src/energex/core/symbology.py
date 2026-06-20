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
    "weather": "bitemporal_replace",
    "prices.spot": "degenerate",
    "prices.intraday": "degenerate",
    "prices.futures": "bitemporal_merge",
    "power.demand": "degenerate",
    "power.demand_forecast": "degenerate",
    "power.generation": "degenerate",
    "power.interchange": "degenerate",
    "power.generation_by_fuel": "degenerate",
    "power.lmp": "bitemporal_merge",
    "power.load": "bitemporal_merge",
    "power.fuelmix": "bitemporal_merge",
}

# Rule-based routing for the high-cardinality power namespace: <PREFIX>.<TAIL> where
# TAIL is the balancing-authority / settlement-point code. Avoids statically enumerating
# the ~60+ EIA-930 balancing authorities (which drift over time). symbol = TAIL lowercased.
_POWER_PREFIX: dict[str, tuple[str, str]] = {
    "EIA930.D": ("power.demand", "degenerate"),
    "EIA930.DF": ("power.demand_forecast", "degenerate"),
    "EIA930.NG": ("power.generation", "degenerate"),
    "EIA930.TI": ("power.interchange", "degenerate"),
    "EIA930.GEN_FUEL": ("power.generation_by_fuel", "degenerate"),
    "ERCOT.SPP": ("power.lmp", "bitemporal_merge"),
    "ERCOT.LOAD": ("power.load", "bitemporal_merge"),
    "ERCOT.FUELMIX": ("power.fuelmix", "bitemporal_merge"),
}


def _resolve_power(instrument_id: str) -> tuple[str, str, str] | None:
    """(library, symbol, mode) for a power instrument_id, or None if not a power id."""
    head, _, tail = instrument_id.rpartition(".")
    entry = _POWER_PREFIX.get(head)
    if entry is None or not tail:
        return None
    library, mode = entry
    return (library, tail.lower(), mode)


# commodity -> ordered list of contract SYMBOL strings (used by read_curve).
_CONTRACTS: dict[str, list[str]] = {
    "crude": ["CL_CLF26", "CL_CLG26"],
}

# Reverse index: symbol -> (library, revision_mode).
_BY_SYMBOL: dict[str, tuple[str, str]] = {
    symbol: (library, mode) for library, symbol, mode in _TABLE.values()
}


def resolve(instrument_id: str) -> tuple[str, str]:
    entry = _TABLE.get(instrument_id)
    if entry is not None:
        return (entry[0], entry[1])
    power = _resolve_power(instrument_id)
    if power is not None:
        return (power[0], power[1])
    raise SymbologyError(f"unknown instrument_id {instrument_id!r}")


def revision_mode(instrument_id: str) -> str:
    entry = _TABLE.get(instrument_id)
    if entry is not None:
        return entry[2]
    power = _resolve_power(instrument_id)
    if power is not None:
        return power[2]
    raise SymbologyError(f"unknown instrument_id {instrument_id!r}")


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
