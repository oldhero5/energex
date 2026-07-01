"""Observer API: internal, role-secured FastAPI over energex.core + Dagster + Neo4j + geo.

Phase 1 wires auth, CORS, /healthz, and the meta + catalog routers. It is the only component
holding data-store credentials; the browser talks to it with a Supabase JWT only.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from energex.observer.routers import catalog, meta, metrics, symbol


def create_app() -> FastAPI:
    app = FastAPI(title="Energex Data Observer API")
    origins = [
        o.strip() for o in os.environ.get("OBSERVER_CORS_ORIGINS", "").split(",") if o.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(meta.router)  # /healthz lives here (open) + /me, /admin/ping
    app.include_router(catalog.router)
    app.include_router(symbol.router)
    app.include_router(metrics.router)
    return app


app = create_app()
