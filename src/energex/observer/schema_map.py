"""Library/symbol -> core.schemas routing. Mirrors orchestration/checks.py's gate assignments;
the constraint definitions live in core.schemas (single source of truth) — only routing is here."""

from __future__ import annotations

import pandera as pa

from energex.core import schemas

_BY_LIBRARY: dict[str, pa.DataFrameSchema] = {
    "prices.spot": schemas.FRED_SPOT,
    "prices.intraday": schemas.OHLCV,
    "prices.futures": schemas.DATED_CONTRACTS,
    "weather": schemas.NOAA_HDDCDD,
    "power.demand": schemas.POWER_REGION,
    "power.demand_forecast": schemas.POWER_REGION,
    "power.generation": schemas.POWER_REGION,
    "power.interchange": schemas.POWER_REGION,
    "power.generation_by_fuel": schemas.POWER_GEN_BY_FUEL,
    "power.lmp": schemas.ERCOT_SPP,
    "power.dalmp": schemas.ERCOT_SPP,
    "power.load": schemas.ERCOT_LOAD,
}
_EIA_BY_SYMBOL: dict[str, pa.DataFrameSchema] = {
    "ng_storage_lower48": schemas.EIA_GAS_STORAGE,
    "pet_crude_stocks": schemas.EIA_PETROLEUM,
}


def schema_for(library: str, symbol: str) -> pa.DataFrameSchema | None:
    if library == "fundamentals.eia":
        return _EIA_BY_SYMBOL.get(symbol)
    return _BY_LIBRARY.get(library)


def describe_schema(schema: pa.DataFrameSchema) -> dict:
    cols = []
    for cname, col in schema.columns.items():
        checks = [str(c) for c in (col.checks or [])]
        cols.append(
            {
                "name": cname,
                "dtype": str(col.dtype),
                "nullable": bool(col.nullable),
                "checks": checks,
            }
        )
    return {
        "schema_name": schema.name,
        "columns": cols,
        "checks": [str(c) for c in (schema.checks or [])],
    }
