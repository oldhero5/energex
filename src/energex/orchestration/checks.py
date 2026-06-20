"""Dagster @asset_check definitions — the single-sourced core.quality gate, post-write.

The check reads the committed bars back from ArcticDB and re-runs the SAME
``core.quality.validate(OHLCV)`` the asset ran (re-localizing valid_time to UTC,
which Arctic strips on store), proving the vintage resolves and still passes the
gate. The freshness wide-check uses the as_of the asset *committed* (max of the
read-back ``as_of`` provenance column), not wall-clock now, so a later check run
cannot false-flag staleness for data that was fresh when written. UI visibility
is best-effort; the real safety net is reconcile.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import dagster as dg
import pandas as pd

from energex.core import quality, schemas, storage, symbology
from energex.core.connectors.eia import (
    EiaGasStorageConnector,
    EiaPetroleumStatusConnector,
)
from energex.core.connectors.fred import INSTRUMENT_IDS as FRED_INSTRUMENT_IDS
from energex.core.connectors.weather import INSTRUMENT_IDS as NOAA_INSTRUMENT_IDS
from energex.core.connectors.yfinance import INSTRUMENT_IDS
from energex.core.exceptions import QualityGateError
from energex.orchestration.assets import (
    EIA_LIBRARY,
    INTRADAY_LIBRARY,
    NOAA_LIBRARY,
    SPOT_LIBRARY,
)
from energex.orchestration.resources import ArcticDBResource


def _committed_as_of(frame: pd.DataFrame) -> datetime:
    """Knowledge time the asset wrote: the max committed ``as_of`` in the read-back
    frame (Arctic strips tz on store, so re-localize to UTC). Using the committed
    as_of — not wall-clock now — keeps the freshness check at the SAME knowledge time
    the asset validated against. Falls back to now only if provenance is absent."""
    if "as_of" in frame.columns and len(frame):
        return pd.to_datetime(frame["as_of"], utc=True).max().to_pydatetime()
    return datetime.now(timezone.utc)


@dg.asset_check(
    asset="intraday_futures_bars",
    name="intraday_bars_pass_quality_gate",
    description="Read-back bars from prices.intraday re-pass the core.quality OHLCV gate.",
)
def intraday_bars_pass_quality_gate(arctic: ArcticDBResource) -> dg.AssetCheckResult:
    lib = arctic.get_library(INTRADAY_LIBRARY)
    frames: list[pd.DataFrame] = []
    for instrument_id in INSTRUMENT_IDS:
        _library, symbol = symbology.resolve(instrument_id)
        if not lib.has_symbol(symbol):
            continue
        df = storage.read_as_of(lib, symbol)
        if not df.empty:
            frames.append(df)

    if not frames:
        return dg.AssetCheckResult(
            passed=False, metadata={"reason": "no bars found in prices.intraday"}
        )

    frame = pd.concat(frames, ignore_index=True)
    frame["valid_time"] = pd.to_datetime(frame["valid_time"], utc=True)  # Arctic stripped tz
    as_of = _committed_as_of(frame)
    try:
        validated = quality.validate(frame, schemas.OHLCV, as_of=as_of)
    except QualityGateError as exc:
        return dg.AssetCheckResult(
            passed=False,
            metadata={"schema": exc.schema_name, "failures": int(len(exc.failures))},
        )

    return dg.AssetCheckResult(
        passed=True,
        metadata={
            "rows": int(len(validated)),
            "symbols": dg.MetadataValue.json(sorted(validated["instrument_id"].unique().tolist())),
        },
    )


@dg.asset_check(
    asset="noaa_degree_days",
    name="noaa_degree_days_pass_quality_gate",
    description="Read-back degree days from the weather library re-pass the NOAA_HDDCDD gate.",
)
def noaa_degree_days_pass_quality_gate(arctic: ArcticDBResource) -> dg.AssetCheckResult:
    lib = arctic.get_library(NOAA_LIBRARY)
    frames: list[pd.DataFrame] = []
    for instrument_id in NOAA_INSTRUMENT_IDS:
        _library, symbol = symbology.resolve(instrument_id)
        if not lib.has_symbol(symbol):
            continue
        df = storage.read_as_of(lib, symbol)
        if not df.empty:
            frames.append(df)

    if not frames:
        return dg.AssetCheckResult(
            passed=False, metadata={"reason": "no degree days found in weather library"}
        )

    frame = pd.concat(frames, ignore_index=True)
    frame["valid_time"] = pd.to_datetime(frame["valid_time"], utc=True)  # Arctic stripped tz
    as_of = _committed_as_of(frame)
    try:
        validated = quality.validate(frame, schemas.NOAA_HDDCDD, as_of=as_of)
    except QualityGateError as exc:
        return dg.AssetCheckResult(
            passed=False,
            metadata={"schema": exc.schema_name, "failures": int(len(exc.failures))},
        )

    return dg.AssetCheckResult(
        passed=True,
        metadata={
            "rows": int(len(validated)),
            "symbols": dg.MetadataValue.json(sorted(validated["instrument_id"].unique().tolist())),
        },
    )


@dg.asset_check(
    asset="fred_spot_prices",
    name="fred_spot_prices_pass_quality_gate",
    description="Read-back spot prices from prices.spot re-pass the core.quality FRED_SPOT gate.",
)
def fred_spot_prices_pass_quality_gate(arctic: ArcticDBResource) -> dg.AssetCheckResult:
    lib = arctic.get_library(SPOT_LIBRARY)
    frames: list[pd.DataFrame] = []
    for instrument_id in FRED_INSTRUMENT_IDS:
        _library, symbol = symbology.resolve(instrument_id)
        if not lib.has_symbol(symbol):
            continue
        df = storage.read_as_of(lib, symbol)
        if not df.empty:
            frames.append(df)

    if not frames:
        return dg.AssetCheckResult(
            passed=False, metadata={"reason": "no spot prices found in prices.spot"}
        )

    frame = pd.concat(frames, ignore_index=True)
    frame["valid_time"] = pd.to_datetime(frame["valid_time"], utc=True)  # Arctic stripped tz
    as_of = _committed_as_of(frame)
    try:
        validated = quality.validate(frame, schemas.FRED_SPOT, as_of=as_of)
    except QualityGateError as exc:
        return dg.AssetCheckResult(
            passed=False,
            metadata={"schema": exc.schema_name, "failures": int(len(exc.failures))},
        )

    return dg.AssetCheckResult(
        passed=True,
        metadata={
            "rows": int(len(validated)),
            "symbols": dg.MetadataValue.json(sorted(validated["instrument_id"].unique().tolist())),
        },
    )


def _eia_gate_readback(
    arctic: ArcticDBResource, instrument_ids: list[str], schema: Any, label: str
) -> dg.AssetCheckResult:
    """Read committed EIA series back from fundamentals.eia and re-run the SAME gate."""
    lib = arctic.get_library(EIA_LIBRARY)
    frames: list[pd.DataFrame] = []
    for instrument_id in instrument_ids:
        _library, symbol = symbology.resolve(instrument_id)
        if not lib.has_symbol(symbol):
            continue
        df = storage.read_as_of(lib, symbol)
        if not df.empty:
            frames.append(df)

    if not frames:
        return dg.AssetCheckResult(
            passed=False, metadata={"reason": f"no {label} in {EIA_LIBRARY}"}
        )

    frame = pd.concat(frames, ignore_index=True)
    frame["valid_time"] = pd.to_datetime(frame["valid_time"], utc=True)  # Arctic stripped tz
    as_of = _committed_as_of(frame)
    try:
        validated = quality.validate(frame, schema, as_of=as_of)
    except QualityGateError as exc:
        return dg.AssetCheckResult(
            passed=False,
            metadata={"schema": exc.schema_name, "failures": int(len(exc.failures))},
        )

    return dg.AssetCheckResult(
        passed=True,
        metadata={
            "rows": int(len(validated)),
            "symbols": dg.MetadataValue.json(sorted(validated["instrument_id"].unique().tolist())),
        },
    )


@dg.asset_check(
    asset="eia_gas_storage",
    name="eia_gas_storage_pass_quality_gate",
    description="Read-back gas storage from fundamentals.eia re-passes the EIA_GAS_STORAGE gate.",
)
def eia_gas_storage_pass_quality_gate(arctic: ArcticDBResource) -> dg.AssetCheckResult:
    return _eia_gate_readback(
        arctic, [EiaGasStorageConnector.instrument_id], schemas.EIA_GAS_STORAGE, "gas storage"
    )


@dg.asset_check(
    asset="eia_petroleum_status",
    name="eia_petroleum_status_pass_quality_gate",
    description="Read-back crude stocks from fundamentals.eia re-passes the EIA_PETROLEUM gate.",
)
def eia_petroleum_status_pass_quality_gate(arctic: ArcticDBResource) -> dg.AssetCheckResult:
    return _eia_gate_readback(
        arctic, [EiaPetroleumStatusConnector.instrument_id], schemas.EIA_PETROLEUM, "crude stocks"
    )


def _power_gate_readback(
    arctic: ArcticDBResource, libraries: list[str], schema: Any, label: str
) -> dg.AssetCheckResult:
    """Read back every symbol across the given power libraries and re-run the gate."""
    frames: list[pd.DataFrame] = []
    for library in libraries:
        lib = arctic.get_library(library)
        for symbol in lib.list_symbols():
            if symbol.endswith("__vintages"):  # skip the version-index sidecars
                continue
            df = storage.read_as_of(lib, symbol)
            if not df.empty:
                frames.append(df)
    if not frames:
        return dg.AssetCheckResult(passed=False, metadata={"reason": f"no {label} found"})
    frame = pd.concat(frames, ignore_index=True)
    frame["valid_time"] = pd.to_datetime(frame["valid_time"], utc=True)
    as_of = _committed_as_of(frame)
    try:
        validated = quality.validate(frame, schema, as_of=as_of)
    except QualityGateError as exc:
        return dg.AssetCheckResult(
            passed=False,
            metadata={"schema": exc.schema_name, "failures": int(len(exc.failures))},
        )
    return dg.AssetCheckResult(
        passed=True,
        metadata={"rows": int(len(validated)), "symbols": int(frame["instrument_id"].nunique())},
    )


@dg.asset_check(
    asset="eia930_region",
    name="eia930_region_pass_quality_gate",
    description="Read-back EIA-930 region series re-pass the POWER_REGION gate.",
)
def eia930_region_pass_quality_gate(arctic: ArcticDBResource) -> dg.AssetCheckResult:
    return _power_gate_readback(
        arctic,
        ["power.demand", "power.demand_forecast", "power.generation", "power.interchange"],
        schemas.POWER_REGION,
        "EIA-930 region series",
    )


@dg.asset_check(
    asset="eia930_generation_by_fuel",
    name="eia930_generation_by_fuel_pass_quality_gate",
    description="Read-back EIA-930 by-fuel generation re-pass the POWER_GEN_BY_FUEL gate.",
)
def eia930_generation_by_fuel_pass_quality_gate(
    arctic: ArcticDBResource,
) -> dg.AssetCheckResult:
    return _power_gate_readback(
        arctic, ["power.generation_by_fuel"], schemas.POWER_GEN_BY_FUEL, "EIA-930 by-fuel"
    )


CHECKS: list[Any] = [
    intraday_bars_pass_quality_gate,
    fred_spot_prices_pass_quality_gate,
    noaa_degree_days_pass_quality_gate,
    eia_gas_storage_pass_quality_gate,
    eia_petroleum_status_pass_quality_gate,
    eia930_region_pass_quality_gate,
    eia930_generation_by_fuel_pass_quality_gate,
]
