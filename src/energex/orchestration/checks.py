"""Dagster @asset_check definitions — the single-sourced core.quality gate, post-write.

The check reads the committed bars back from ArcticDB and re-runs the SAME
``core.quality.validate(OHLCV)`` the asset ran (re-localizing valid_time to UTC,
which Arctic strips on store), proving the vintage resolves and still passes the
gate. UI visibility is best-effort; the real safety net is reconcile.py.
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
from energex.core.connectors.weather import INSTRUMENT_IDS as NOAA_INSTRUMENT_IDS
from energex.core.connectors.yfinance import INSTRUMENT_IDS
from energex.core.exceptions import QualityGateError
from energex.orchestration.assets import EIA_LIBRARY, INTRADAY_LIBRARY, NOAA_LIBRARY
from energex.orchestration.resources import ArcticDBResource


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
    try:
        validated = quality.validate(frame, schemas.OHLCV, as_of=datetime.now(timezone.utc))
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
    try:
        validated = quality.validate(frame, schemas.NOAA_HDDCDD, as_of=datetime.now(timezone.utc))
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
    try:
        validated = quality.validate(frame, schema, as_of=datetime.now(timezone.utc))
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


CHECKS: list[Any] = [
    intraday_bars_pass_quality_gate,
    noaa_degree_days_pass_quality_gate,
    eia_gas_storage_pass_quality_gate,
    eia_petroleum_status_pass_quality_gate,
]
