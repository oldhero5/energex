"""S2 read API: a thin, read-only FastAPI seam over ``energex.core.storage``.

This is the ONLY contract the (separate, private) frontend repo consumes. It is
point-in-time first: every data endpoint takes an optional ``as_of`` (ISO datetime)
and defaults to the latest committed vintage. It opens ArcticDB read-only using the
same URI grammar/config as ``orchestration.ArcticDBResource`` -- creds come from env
(MINIO_* / ARCTIC_BUCKET) and the connection URI embeds the secret (ArcticDB S3
requirement), so the URI is NEVER logged.

Run with ``uvicorn energex.service.readapi:app --workers 1``. The legacy DuckDB serving
app (``energex.service.app``) and APScheduler were removed; this is the S2 replacement.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

# arcticdb MUST be imported before pandas/pyarrow (phase-0 AWS-SDK load-order hazard).
import arcticdb  # noqa: F401
import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from energex.core import storage
from energex.core.config import get_settings

logger = logging.getLogger(__name__)

VINTAGE_SUFFIX = "__vintages"


def _resolve_arctic_uri() -> str:
    """Resolve the Arctic URI: an explicit ``ENERGEX_ARCTIC_URI`` (tests / lmdb) wins;
    otherwise build the S3-on-MinIO URI from config using the ArcticDBResource grammar.

    The built URI embeds the S3 secret, so it is exported into ``ENERGEX_ARCTIC_URI``
    (so ``storage.read_curve`` opens the SAME store) but is NEVER returned to callers
    or logged.
    """
    uri = os.environ.get("ENERGEX_ARCTIC_URI")
    if uri:
        return uri
    cfg = get_settings().arctic
    access = cfg.minio_access_key.get_secret_value() if cfg.minio_access_key else ""
    secret = cfg.minio_secret_key.get_secret_value() if cfg.minio_secret_key else ""
    host, _, port = cfg.minio_endpoint.partition(":")
    port = port or ("443" if cfg.arctic_secure else "9000")
    scheme = "s3s" if cfg.arctic_secure else "s3"
    uri = (
        f"{scheme}://{host}:{cfg.minio_bucket}"
        f"?access={access}&secret={secret}"
        f"&port={port}&use_virtual_addressing=false"
    )
    # read_curve opens its own client from this env var -> point both at one store.
    os.environ["ENERGEX_ARCTIC_URI"] = uri
    return uri


def _records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """pandas frame (DatetimeIndex 'Datetime' + provenance cols incl.
    ``vintage_reconstructed``) -> JSON-safe records with ISO timestamps and NaN->null."""
    if df is None or df.empty:
        return []
    out = df.reset_index()  # surface the 'Datetime' index as a column
    return json.loads(out.to_json(orient="records", date_format="iso"))


def _parse_dt(value: str | None, field: str) -> Any:
    if value is None:
        return None
    try:
        return pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid {field}: {value!r}") from exc


def _latest_as_of(ac: Any) -> str | None:
    """Latest committed knowledge time across all symbols. Reads only the small
    ``*__vintages`` sidecars (not the heavy series data), so healthz stays cheap."""
    latest: pd.Timestamp | None = None
    for lib_name in ac.list_libraries():
        lib = ac[lib_name]
        for sym in lib.list_symbols():
            if not sym.endswith(VINTAGE_SUFFIX):
                continue
            df = lib.read(sym).data
            if "as_of" in df.columns and len(df):
                m = pd.to_datetime(df["as_of"]).max()
                if latest is None or m > latest:
                    latest = m
    return latest.isoformat() if latest is not None else None


def _get_library(ac: Any, library: str) -> Any:
    if library not in ac.list_libraries():
        raise HTTPException(status_code=404, detail=f"unknown library: {library!r}")
    return ac[library]


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from arcticdb import Arctic

        # The URI embeds the S3 secret -> never log it; redact on failure so the
        # credential cannot leak through a connection-error traceback.
        uri = _resolve_arctic_uri()
        try:
            app.state.arctic = Arctic(uri)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("ArcticDB connection failed: %s", type(exc).__name__)
            raise
        logger.info("energex S2 read API started")
        try:
            yield
        finally:
            app.state.arctic = None
            logger.info("energex S2 read API stopped")

    app = FastAPI(title="energex S2 read API", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        ac = app.state.arctic
        libraries = ac.list_libraries()
        try:
            latest = _latest_as_of(ac)
        except Exception:  # pragma: no cover - health must not fail on the latest probe
            latest = None
        return {"status": "ok", "libraries": libraries, "latest_as_of": latest}

    @app.get("/libraries")
    def libraries() -> list[str]:
        return list(app.state.arctic.list_libraries())

    @app.get("/symbols")
    def symbols(library: str = Query(...)) -> list[str]:
        lib = _get_library(app.state.arctic, library)
        return [s for s in lib.list_symbols() if not s.endswith(VINTAGE_SUFFIX)]

    @app.get("/series")
    def series(
        library: str = Query(...),
        symbol: str = Query(...),
        as_of: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        lib = _get_library(app.state.arctic, library)
        if symbol not in lib.list_symbols():
            raise HTTPException(status_code=404, detail=f"unknown symbol: {symbol!r}")
        when = _parse_dt(as_of, "as_of")
        lo, hi = _parse_dt(start, "start"), _parse_dt(end, "end")
        date_range = (lo, hi) if (lo is not None or hi is not None) else None
        df = storage.read_as_of(lib, symbol, as_of=when, date_range=date_range)
        return _records(df)

    @app.get("/curve")
    def curve(
        commodity: str = Query(...), as_of: str | None = Query(default=None)
    ) -> list[dict[str, Any]]:
        when = _parse_dt(as_of, "as_of")
        df = storage.read_curve(commodity, when)
        return _records(df)

    return app


app = create_app()
