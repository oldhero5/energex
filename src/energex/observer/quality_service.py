"""Per-symbol veracity: re-run the platform's pandera gate against stored data (the SAME definition
of broken the pipeline uses), plus valid_time gap counting and OHLCV anomaly summary. On-demand only.
"""

from __future__ import annotations

import datetime as dt

import polars as pl

from energex.analysis.quality import DataQualityChecker
from energex.core import quality, storage, symbology
from energex.core.exceptions import QualityGateError
from energex.observer.arctic import get_arctic
from energex.observer.schema_map import schema_for

_OHLCV_COLS = {"Open", "High", "Low", "Close", "Volume"}


def _failures_to_list(failures) -> list[dict]:
    try:
        rows = failures.to_dict(orient="records")
    except Exception:
        return [{"check": str(failures)}]
    return [
        {
            "check": str(r.get("check", "")),
            "column": str(r.get("column", "")),
            "failure_case": str(r.get("failure_case", "")),
        }
        for r in rows
    ][:50]


def symbol_quality(library: str, symbol: str, as_of: dt.datetime | None = None) -> dict:
    lib = get_arctic()[library]
    mode = symbology.mode_for_library(library)
    df = storage.read_as_of(lib, symbol, as_of=as_of, mode=mode)
    schema = schema_for(library, symbol)
    result: dict = {
        "library": library,
        "symbol": symbol,
        "schema_name": schema.name if schema else None,
        "passed": None,
        "failures": [],
        "gaps": 0,
        "anomalies": None,
    }
    if schema is not None:
        try:
            quality.validate(df.reset_index(), schema, as_of=dt.datetime.now(dt.timezone.utc))
            result["passed"] = True
        except QualityGateError as exc:
            result["passed"] = False
            result["failures"] = _failures_to_list(exc.failures)
    # valid_time gaps: count distinct missing steps at the modal cadence
    if "valid_time" in df.columns and len(df) > 2:
        vt = pl.Series(df["valid_time"].sort_values().to_numpy())
        deltas = vt.diff().drop_nulls()
        if len(deltas):
            modal = deltas.mode().to_list()[0]
            result["gaps"] = int((deltas > modal).sum()) if modal else 0
    # OHLCV-only anomaly summary (requires Symbol and Datetime columns)
    if _OHLCV_COLS.issubset(set(df.columns)):
        try:
            result["anomalies"] = DataQualityChecker(
                pl.from_pandas(df.reset_index())
            ).check_tick_quality()
        except Exception:
            result["anomalies"] = None
    return result
