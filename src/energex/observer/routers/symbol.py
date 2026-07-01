from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException

from energex.core import storage, symbology
from energex.observer.arctic import VINTAGE_SUFFIX, get_arctic
from energex.observer.auth import Role, require_role
from energex.observer.quality_service import symbol_quality
from energex.observer.schema_map import describe_schema, schema_for

router = APIRouter(prefix="/symbol/{library}/{symbol}")


def _parse(ts: str | None):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def _lib_or_404(library: str):
    ac = get_arctic()
    if library not in ac.list_libraries():
        raise HTTPException(404, f"unknown library {library!r}")
    return ac[library]


def _mode_for_library(library: str) -> str | None:
    try:
        return symbology.mode_for_library(library)
    except Exception:
        return None


@router.get("/series")
def series(
    library: str,
    symbol: str,
    as_of: str | None = None,
    start: str | None = None,
    end: str | None = None,
    _c: dict = require_role(Role.viewer),  # noqa: B008
) -> dict:
    lib = _lib_or_404(library)
    dr = (_parse(start), _parse(end)) if (start or end) else None
    mode = _mode_for_library(library)
    try:
        df = storage.read_as_of(lib, symbol, as_of=_parse(as_of), date_range=dr, mode=mode)
    except Exception as exc:
        raise HTTPException(404, f"cannot read {symbol!r}: {exc}") from exc
    out = df.reset_index()
    for col in out.columns:
        if str(out[col].dtype).startswith("datetime"):
            out[col] = out[col].astype(str)
    return {"library": library, "symbol": symbol, "rows": out.to_dict(orient="records")}


@router.get("/schema")
def schema(
    library: str,
    symbol: str,
    _c: dict = require_role(Role.viewer),  # noqa: B008
) -> dict:
    sch = schema_for(library, symbol)
    if sch is None:
        return {
            "library": library,
            "symbol": symbol,
            "schema_name": None,
            "columns": [],
            "checks": [],
        }
    return {"library": library, "symbol": symbol, **describe_schema(sch)}


@router.get("/quality")
def quality_endpoint(
    library: str,
    symbol: str,
    as_of: str | None = None,
    _c: dict = require_role(Role.viewer),  # noqa: B008
) -> dict:
    _lib_or_404(library)
    return symbol_quality(library, symbol, as_of=_parse(as_of))


@router.get("/vintages")
def vintages(
    library: str,
    symbol: str,
    _c: dict = require_role(Role.viewer),  # noqa: B008
) -> dict:
    lib = _lib_or_404(library)
    try:
        v = lib.read(f"{symbol}{VINTAGE_SUFFIX}").data.reset_index(drop=True)
    except Exception:
        return {"library": library, "symbol": symbol, "vintages": []}  # degenerate: no sidecar
    for col in v.columns:
        if str(v[col].dtype).startswith("datetime"):
            v[col] = v[col].astype(str)
    return {"library": library, "symbol": symbol, "vintages": v.to_dict(orient="records")}
