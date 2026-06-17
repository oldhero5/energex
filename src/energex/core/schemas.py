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
    s = pd.Timestamp(start).tz_convert("UTC").tz_localize(None).normalize()
    e = pd.Timestamp(end).tz_convert("UTC").tz_localize(None).normalize()
    if e <= s:
        return 0
    return int(np.busday_count(s.date(), e.date()))


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

EIA_GAS_STORAGE = DataFrameSchema(
    name="EIA_GAS_STORAGE",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        "value": Column(float, Check.ge(0), nullable=False, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(6)],
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
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(6)],
    strict=False,
    coerce=True,
)

ERCOT_DALMP = DataFrameSchema(
    name="ERCOT_DALMP",
    columns={
        "instrument_id": _id_col(),
        "valid_time": _valid_time_col(),
        # Sane day-ahead LMP band ($/MWh): negative pricing happens; cap absurd values.
        "lmp": Column(float, Check.in_range(-250.0, 5000.0), nullable=False, coerce=True),
    },
    checks=[_unique_keys_check(), _row_floor_check(), _freshness_check(3)],
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
