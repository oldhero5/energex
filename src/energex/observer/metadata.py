"""Cheap catalog metadata: lib.get_description() (row_count + max valid_time, no data read) plus
the vintage sidecar for bitemporal symbols. Never reads full symbol data."""

from __future__ import annotations

import logging

from energex.core import symbology
from energex.observer.arctic import VINTAGE_SUFFIX, get_arctic
from energex.observer.schema_map import schema_for

logger = logging.getLogger(__name__)


def _description(lib, symbol):
    """(row_count, latest_valid_time) via ArcticDB get_description, no data read.
    Attribute names verified against installed arcticdb: row_count (int) and
    date_range (tuple of tz-naive Timestamps). Falls back to 0/None on error."""
    desc = lib.get_description(symbol)
    row_count = int(getattr(desc, "row_count", 0) or 0)
    date_range = getattr(desc, "date_range", (None, None))
    latest_valid_time = (
        date_range[1].isoformat() if date_range and date_range[1] is not None else None
    )
    return row_count, latest_valid_time


def _vintage_meta(lib, symbol):
    """(vintage_count, reconstructed_pct) for bitemporal symbols; (None, None) if no sidecar."""
    try:
        v = lib.read(f"{symbol}{VINTAGE_SUFFIX}").data
    except Exception:
        return None, None
    n = len(v)
    pct = round(100.0 * float(v["vintage_reconstructed"].mean()), 1) if n else 0.0
    return n, pct


def _symbol_meta(lib, library, symbol, mode="unknown"):
    row_count, latest_valid_time = _description(lib, symbol)
    if "bitemporal" in mode:
        vintage_count, reconstructed_pct = _vintage_meta(lib, symbol)
    else:
        vintage_count, reconstructed_pct = None, None
    schema = schema_for(library, symbol)
    return {
        "symbol": symbol,
        "row_count": row_count,
        "latest_valid_time": latest_valid_time,
        "vintage_count": vintage_count,
        "reconstructed_pct": reconstructed_pct,
        "schema_name": schema.name if schema is not None else None,
    }


def list_catalog() -> dict:
    ac = get_arctic()
    libraries = []
    for name in sorted(ac.list_libraries()):
        lib = ac[name]
        try:
            mode = symbology.mode_for_library(name)
        except Exception:
            mode = "unknown"
        syms = [s for s in lib.list_symbols() if not s.endswith(VINTAGE_SUFFIX)]
        out, unreadable = [], 0
        for s in sorted(syms):
            try:
                out.append(_symbol_meta(lib, name, s, mode=mode))
            except Exception:
                logger.warning("metadata: symbol %r in %r unreadable — skipping", s, name)
                unreadable += 1
        libraries.append({"name": name, "mode": mode, "symbols": out, "unreadable": unreadable})
    return {"libraries": libraries}
