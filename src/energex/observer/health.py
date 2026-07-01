"""Per-symbol freshness heuristic, cached with a TTL. Cheap: max valid_time (get_description) vs a
per-schema business-day tolerance mirroring schemas.py. NOT the full gate (that's quality_service)."""

from __future__ import annotations

import datetime as dt
import os
import time

import numpy as np

from energex.core.schemas import _EIA_FRESHNESS_DAYS, _FRED_FRESHNESS_DAYS
from energex.observer.arctic import get_arctic
from energex.observer.metadata import _description
from energex.observer.schema_map import schema_for

# Mirror of schemas.py freshness days; a test cross-checks the importable ones.
_FRESHNESS_DAYS: dict[str, int] = {
    "OHLCV": 2,
    "DATED_CONTRACTS": 5,
    "EIA_GAS_STORAGE": _EIA_FRESHNESS_DAYS,
    "EIA_PETROLEUM": _EIA_FRESHNESS_DAYS,
    "FRED_SPOT": _FRED_FRESHNESS_DAYS,
    "ERCOT_SPP": 2,
    "ERCOT_LOAD": 2,
    "POWER_REGION": 2,
    "POWER_GEN_BY_FUEL": 2,
    "NOAA_HDDCDD": 45,
}

_TTL: int = int(os.environ.get("OBSERVER_HEALTH_TTL_SECONDS", "300"))

# (library, symbol) -> (monotonic_timestamp, row_dict)
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _business_days_since(latest_iso: str | None) -> int | None:
    if not latest_iso:
        return None
    latest = dt.datetime.fromisoformat(latest_iso)
    now = dt.datetime.now(dt.timezone.utc)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=dt.timezone.utc)
    return int(np.busday_count(latest.date(), now.date()))


def _compute(library: str, symbol: str) -> dict:
    lib = get_arctic()[library]
    schema = schema_for(library, symbol)
    try:
        row_count, latest_valid_time = _description(lib, symbol)
    except Exception:
        return {
            "symbol": symbol,
            "freshness_status": "error",
            "age_days": None,
            "latest_valid_time": None,
            "row_count": None,
            "vintage_count": None,
            "reconstructed_pct": None,
        }
    age = _business_days_since(latest_valid_time)
    tol = _FRESHNESS_DAYS.get(schema.name) if schema else None
    if age is None:
        status = "error"
    elif tol is not None and age > tol:
        status = "stale"
    else:
        status = "ok"
    vc = rp = None
    try:
        from energex.observer.arctic import VINTAGE_SUFFIX

        v = lib.read(f"{symbol}{VINTAGE_SUFFIX}").data
        vc = len(v)
        rp = round(100.0 * float(v["vintage_reconstructed"].mean()), 1) if vc else 0.0
    except Exception:
        pass
    return {
        "symbol": symbol,
        "freshness_status": status,
        "age_days": age,
        "latest_valid_time": latest_valid_time,
        "row_count": row_count,
        "vintage_count": vc,
        "reconstructed_pct": rp,
    }


def health_row(library: str, symbol: str) -> dict:
    key = (library, symbol)
    hit = _cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _TTL:
        return hit[1]
    row = _compute(library, symbol)
    _cache[key] = (time.monotonic(), row)
    return row
