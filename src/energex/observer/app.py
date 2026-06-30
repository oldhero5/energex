"""Observer API: internal, role-secured FastAPI over energex.core + Dagster + Neo4j + geo.

Phase 1 wires auth, CORS, /healthz, and the meta + catalog routers. It is the only component
holding data-store credentials; the browser talks to it with a Supabase JWT only.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from energex.observer.config import ObserverSettings
from energex.observer.routers import catalog, meta


def create_app() -> FastAPI:
    app = FastAPI(title="Energex Data Observer API")
    origins = ObserverSettings().origins
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    app.include_router(meta.router)
    app.include_router(catalog.router)
    return app


app = create_app()
