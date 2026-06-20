"""Pandera quality-gate schemas for the Energex bitemporal data platform.

These are the PRE-WRITE gate schemas, distinct from analysis/quality.py's
post-hoc DataQualityChecker. ``core.quality.validate`` runs these and raises
``QualityGateError`` on any failure. Each schema enforces column presence and
dtype, non-null (instrument_id, valid_time), value sanity bands, a row-count
floor, and two DataFrame-level wide checks: (instrument_id, valid_time)
uniqueness and a release-calendar-aware freshness bound on max(valid_time).
"""

from __future__ import annotations

import contextvars
from datetime import datetime

import numpy as np
import pandas as pd
from pandera.pandas import Check, Column, DataFrameSchema

# ``as_of`` is supplied per ``validate`` call; freshness wide-checks read it.
AS_OF: contextvars.ContextVar[datetime] = contextvars.ContextVar("energex_quality_as_of")

# NOAA nClimDiv fixed-width "missing" sentinel; coerced to NULL before checks.
NOAA_SENTINEL = -9999.0

# Common column dtypes.
_UTC = "datetime64[ns, UTC]"


def _business_days_between(start, end) -> int:
    """Count business days (Mon-Fri) from ``start`` up to ``end``.

    Release-calendar-aware: weekends do not count toward staleness, so a
    Monday as_of is not falsely flagged stale for a Friday valid_time. Future
    valid_time (start > end) is treated as zero lag (not stale).
    """
    if pd.isna(start) or pd.isna(end):
        return 0
    s = _to_naive_utc(start).normalize()
    e = _to_naive_utc(end).normalize()
    if e <= s:
        return 0
    return int(np.busday_count(s.date(), e.date()))


def _to_naive_utc(value) -> pd.Timestamp:
    """Coerce any datetime-like to a tz-naive UTC ``pd.Timestamp``.

    tz-naive input is assumed UTC (localize), tz-aware input is converted; both
    end up tz-naive so ``np.busday_count`` can take ``.date()``.
    """
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.tz_localize(None)


def _freshness_check(max_business_days: int) -> Check:
    """Wide check: max(valid_time) within ``max_business_days`` of as_of."""

    def _check(df: pd.DataFrame) -> bool:
        if df.empty or "valid_time" not in df.columns:
            return False
        as_of = AS_OF.get()
        latest = df["valid_time"].max()
        return _business_days_between(latest, pd.Timestamp(as_of)) <= max_business_days

    return Check(
        _check,
        error=f"max(valid_time) staler than {max_business_days} business days from as_of",
    )


def _unique_keys_check() -> Check:
    """Wide check: (instrument_id, valid_time) must be unique."""

    def _check(df: pd.DataFrame) -> bool:
        if {"instrument_id", "valid_time"} - set(df.columns):
            return False
        return not df.duplicated(subset=["instrument_id", "valid_time"]).any()

    return Check(_check, error="(instrument_id, valid_time) is not unique")


def _unique_keys_check_with(extra_cols: tuple[str, ...]) -> Check:
    """Wide check: (instrument_id, valid_time, *extra_cols) must be unique."""
    keys = ["instrument_id", "valid_time", *extra_cols]

    def _check(df: pd.DataFrame) -> bool:
        if set(keys) - set(df.columns):
            return False
        return not df.duplicated(subset=keys).any()

    return Check(_check, error=f"{tuple(keys)} is not unique")


def _row_floor_check(min_rows: int = 1) -> Check:
    """Wide check: empty (or below-floor) frames fail."""

    def _check(df: pd.DataFrame) -> bool:
        return len(df) >= min_rows

    return Check(_check, error=f"row-count below floor ({min_rows})")


def _id_col() -> Column:
    return Column(str, nullable=False)


def _valid_time_col() -> Column:
    return Column(_UTC, nullable=False, coerce=False)


def _ohlcv_value_cols() -> dict:
    return {
        "Open": Column(float, Check.ge(0), nullable=False, coerce=True),
        "High": Column(float, Check.ge(0), nullable=False, coerce=True),
        "Low": Column(float, Check.ge(0), nullable=False, coerce=True),
        "Close": Column(float, Check.ge(0), nullable=False, coerce=True),
        "Volume": Column("int64", Check.ge(0), nullable=False, coerce=True),
    }


OHLCV = DataFrameSchema(
    name="OHLCV",
    columns={"instrument_id": _id_col(), "valid_time": _valid_time_col(), **_ohlcv_value_cols()},
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(2)],
    strict=False,
    coerce=True,
)

DATED_CONTRACTS = DataFrameSchema(
    name="DATED_CONTRACTS",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "ContractMonth": Column("datetime64[ns]", nullable=False, coerce=True),
        **_ohlcv_value_cols(),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(5)],
    strict=False,
    coerce=True,
)

# EIA weekly series carry a Friday-period -> mid-next-week-release lag (gas storage
# releases Thu, crude stocks Wed) plus a full 5-business-day inter-release gap, so the
# latest available period can be ~9 business days old just before the next release.
# A 10-business-day (two work-week) freshness bound covers the weekly cadence robustly.
_EIA_FRESHNESS_DAYS = 10

EIA_GAS_STORAGE = DataFrameSchema(
    name="EIA_GAS_STORAGE",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "value": Column(float, Check.ge(0), nullable=False, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(_EIA_FRESHNESS_DAYS)],
    strict=False,
    coerce=True,
)

EIA_PETROLEUM = DataFrameSchema(
    name="EIA_PETROLEUM",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "value": Column(float, Check.ge(0), nullable=False, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(_EIA_FRESHNESS_DAYS)],
    strict=False,
    coerce=True,
)

# FRED publishes daily benchmark spot prices on business days only, with a few-business-day
# lag (the latest available observation can be ~3-4 business days old). A 7-business-day
# freshness bound covers that publication lag with margin.
_FRED_FRESHNESS_DAYS = 7

FRED_SPOT = DataFrameSchema(
    name="FRED_SPOT",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "value": Column(float, Check.ge(0), nullable=False, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(_FRED_FRESHNESS_DAYS)],
    strict=False,
    coerce=True,
)

ERCOT_SPP = DataFrameSchema(
    name="ERCOT_SPP",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "settlement_point": Column(str, nullable=False),
        # Settlement Point Price band ($/MWh): ERCOT allows -$251 floor / $5000 cap.
        "price": Column(float, Check.in_range(-251.0, 5001.0), nullable=False, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(2)],
    strict=False,
    coerce=True,
)

ERCOT_LOAD = DataFrameSchema(
    name="ERCOT_LOAD",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "value": Column(float, Check.in_range(0.0, 200_000.0), nullable=False, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(2)],
    strict=False,
    coerce=True,
)

ERCOT_FUELMIX = DataFrameSchema(
    name="ERCOT_FUELMIX",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "fuel_type": Column(str, nullable=False),
        "value": Column(float, Check.in_range(-10_000.0, 200_000.0), nullable=True, coerce=True),
    },
    checks=[_unique_keys_check_with(("fuel_type",)), _row_floor_check(), _freshness_check(2)],
    strict=False,
    coerce=True,
)

# EIA-930 hourly grid monitor. value: MWh (demand/generation) or net MWh (interchange,
# signed); EIA publishes gaps as null. Hourly data finalizes within ~1 day -> 2-bday bound.
_POWER_BAND = Check.in_range(-10_000_000.0, 10_000_000.0)

POWER_REGION = DataFrameSchema(
    name="POWER_REGION",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "respondent": Column(str, nullable=False),
        "value": Column(float, _POWER_BAND, nullable=True, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(2)],
    strict=False,
    coerce=True,
)

POWER_GEN_BY_FUEL = DataFrameSchema(
    name="POWER_GEN_BY_FUEL",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "respondent": Column(str, nullable=False),
        "fuel_type": Column(str, nullable=False),
        "value": Column(float, _POWER_BAND, nullable=True, coerce=True),
    },
    checks=[_unique_keys_check_with(("fuel_type",)), _row_floor_check(), _freshness_check(2)],
    strict=False,
    coerce=True,
)


def coerce_noaa_sentinel(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace the -9999. fixed-width sentinel with NULL BEFORE range checks."""
    out = frame.copy()
    for col in ("hdd", "cdd"):
        if col in out.columns:
            out[col] = out[col].replace(NOAA_SENTINEL, np.nan)
    return out


NOAA_HDDCDD = DataFrameSchema(
    name="NOAA_HDDCDD",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "hdd": Column(float, Check.in_range(0.0, 9999.0), nullable=True, coerce=True),
        "cdd": Column(float, Check.in_range(0.0, 9999.0), nullable=True, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(45)],
    strict=False,
    coerce=True,
)

# Per-schema pre-validation transforms applied by core.quality.validate, keyed
# on schema.name (e.g. NOAA sentinel -> NULL before the 0-9999 range check).
PREPROCESSORS = {"NOAA_HDDCDD": coerce_noaa_sentinel}
