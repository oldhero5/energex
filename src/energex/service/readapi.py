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

import hmac
import json
import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

# arcticdb MUST be imported before pandas/pyarrow (phase-0 AWS-SDK load-order hazard).
import arcticdb  # noqa: F401
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from energex.core import graph, storage, symbology
from energex.core.config import get_settings
from energex.core.exceptions import GraphError, SymbologyError

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


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Optional API-key gate. When ``ENERGEX_READ_API_KEY`` is set, every data endpoint requires
    a matching ``X-API-Key`` header (constant-time compared); unset leaves the API open (a startup
    warning is logged). This lets an operator lock down the host-published read API without
    breaking same-host callers that have the key."""
    expected = os.environ.get("ENERGEX_READ_API_KEY")
    if expected and not (x_api_key and hmac.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="missing or invalid API key")


def _get_graph_driver(app: FastAPI) -> Any:
    """Lazily connect the entity-graph driver on first use (the neo4j service is
    optional and may start after the api). Serialized by a lock: endpoints run in
    FastAPI's threadpool. 503 when the graph is genuinely unreachable."""
    if app.state.neo4j is None:
        with app.state.neo4j_lock:
            if app.state.neo4j is None:
                try:
                    app.state.neo4j = graph.create_driver(get_settings().neo4j)
                except GraphError as exc:
                    logger.warning("entity graph unavailable: %s", exc)
                    raise HTTPException(status_code=503, detail="entity graph unavailable") from exc
    return app.state.neo4j


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
        # The entity graph is OPTIONAL: never fail startup on it. Connect lazily
        # so a late-starting neo4j container is picked up by the first /graph/*
        # request rather than requiring an api restart.
        app.state.neo4j = None
        app.state.neo4j_lock = threading.Lock()
        logger.info("energex S2 read API started")
        try:
            yield
        finally:
            if app.state.neo4j is not None:
                app.state.neo4j.close()
                app.state.neo4j = None
            app.state.arctic = None
            logger.info("energex S2 read API stopped")

    app = FastAPI(title="energex S2 read API", lifespan=lifespan)

    # CORS is opt-in and origin-scoped: ENERGEX_CORS_ORIGINS is a comma-separated allow-list
    # (e.g. the frontend origin). Unset = no cross-origin access (the safe default).
    origins = [
        o.strip() for o in os.environ.get("ENERGEX_CORS_ORIGINS", "").split(",") if o.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"]
        )
    if not os.environ.get("ENERGEX_READ_API_KEY"):
        logger.warning(
            "read API is UNAUTHENTICATED — set ENERGEX_READ_API_KEY to require an X-API-Key header"
        )

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        ac = app.state.arctic
        libraries = ac.list_libraries()
        try:
            latest = _latest_as_of(ac)
        except Exception:  # pragma: no cover - health must not fail on the latest probe
            latest = None
        return {
            "status": "ok",
            "libraries": libraries,
            "latest_as_of": latest,
            # Cached state only (no connect attempt): the compose healthcheck
            # budget is 5s and the graph is optional. True after the first
            # successful /graph/* call.
            "graph": app.state.neo4j is not None,
        }

    @app.get("/libraries", dependencies=[Depends(_require_api_key)])
    def libraries() -> list[str]:
        return list(app.state.arctic.list_libraries())

    @app.get("/symbols", dependencies=[Depends(_require_api_key)])
    def symbols(library: str = Query(...)) -> list[str]:
        lib = _get_library(app.state.arctic, library)
        return [s for s in lib.list_symbols() if not s.endswith(VINTAGE_SUFFIX)]

    @app.get("/series", dependencies=[Depends(_require_api_key)])
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
        # Mode is a property of the library; pass it so high-cardinality power.*
        # symbols (bare BA/settlement-point codes) need not be in the static index.
        try:
            mode = symbology.mode_for_library(library)
        except SymbologyError:
            mode = None  # unknown library -> fall back to symbol-based routing
        df = storage.read_as_of(lib, symbol, as_of=when, date_range=date_range, mode=mode)
        # Cap an unbounded full-history read so a single request cannot serialize an arbitrarily
        # large series into one response; intentional bounded reads (start/end) are exempt.
        max_rows = int(os.environ.get("ENERGEX_SERIES_MAX_ROWS", "500000"))
        if date_range is None and df is not None and len(df) > max_rows:
            raise HTTPException(
                status_code=413,
                detail=f"series has {len(df)} rows (> {max_rows}); narrow with start/end",
            )
        return _records(df)

    @app.get("/curve", dependencies=[Depends(_require_api_key)])
    def curve(
        commodity: str = Query(...), as_of: str | None = Query(default=None)
    ) -> list[dict[str, Any]]:
        when = _parse_dt(as_of, "as_of")
        try:
            df = storage.read_curve(commodity, when)
        except SymbologyError as exc:
            raise HTTPException(
                status_code=404, detail=f"unknown commodity: {commodity!r}"
            ) from exc
        return _records(df)

    @app.get("/graph/entities", dependencies=[Depends(_require_api_key)])
    def graph_entities(label: str | None = Query(default=None)) -> list[dict[str, Any]]:
        if label is not None and label not in graph.KEY_PROPERTY:
            raise HTTPException(status_code=404, detail=f"unknown label: {label!r}")
        driver = _get_graph_driver(app)
        try:
            return graph.list_entities(driver, label=label)
        except GraphError as exc:
            raise HTTPException(status_code=503, detail="entity graph unavailable") from exc

    @app.get("/graph/related", dependencies=[Depends(_require_api_key)])
    def graph_related(
        instrument_id: str = Query(...),
        depth: int = Query(default=2, ge=1, le=3),
    ) -> dict[str, Any]:
        driver = _get_graph_driver(app)
        try:
            result = graph.related_instruments(driver, instrument_id, depth=depth)
        except GraphError as exc:
            raise HTTPException(status_code=503, detail="entity graph unavailable") from exc
        if result is None:
            raise HTTPException(status_code=404, detail=f"unknown instrument: {instrument_id!r}")
        return result

    return app


app = create_app()
