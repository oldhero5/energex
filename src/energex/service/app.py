"""FastAPI application: serves stored analytics and runs scheduled ingestion.

Single process, single DuckDB read-write connection owned by the app (DuckDB is
single-writer-per-file). Run with ``uvicorn energex.service.app:app --workers 1``.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import polars as pl
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from energex.analysis.futures import FuturesAnalyzer
from energex.analysis.volatility import VolatilityAnalyzer
from energex.config import get_settings
from energex.database import EnergyDatabase
from energex.logging_config import setup_logging
from energex.service.pipeline import run_ingestion
from energex.service.scheduler import build_scheduler
from energex.visualization.charts import MarketVisualizer

logger = logging.getLogger(__name__)

DEFAULT_CRON = os.environ.get("ENERGEX_INGEST_CRON", "*/5 * * * *")


def _read_df(db: EnergyDatabase, query: str, params: list[Any] | None = None) -> pl.DataFrame:
    """Run a read query on a separate cursor and return a Polars DataFrame."""
    cur = db.conn.cursor()
    table = cur.execute(query, params or []).arrow()
    result = pl.from_arrow(table)
    assert isinstance(result, pl.DataFrame)
    return result


def create_app(db_path: str | None = None, start_scheduler: bool = True) -> FastAPI:
    settings = get_settings()
    resolved_db_path = db_path or str(settings.database.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging(
            log_level=settings.logging.log_level,
            log_file=settings.logging.log_file,
            enable_console=settings.logging.log_enable_console,
        )
        db = EnergyDatabase(resolved_db_path)
        app.state.db = db
        app.state.scheduler = None
        if start_scheduler:
            scheduler = build_scheduler(lambda: run_ingestion(db), cron=DEFAULT_CRON)
            scheduler.start()
            app.state.scheduler = scheduler
        logger.info("energex service started (db=%s)", resolved_db_path)
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown(wait=False)
            db.conn.close()
            logger.info("energex service stopped")

    app = FastAPI(title="energex", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        db: EnergyDatabase = app.state.db
        try:
            row = (
                db.conn.cursor()
                .execute("SELECT COUNT(*), MAX(Datetime) FROM intraday_prices")
                .fetchone()
            )
        except Exception as e:  # pragma: no cover - defensive
            raise HTTPException(status_code=503, detail=f"database error: {e}") from e
        count, latest = row if row is not None else (0, None)
        return {
            "status": "ok",
            "rows": count,
            "latest": latest.isoformat() if latest else None,
        }

    @app.get("/prices")
    def prices(symbol: str = Query(...), limit: int = 100) -> list[dict[str, Any]]:
        df = _read_df(
            app.state.db,
            "SELECT * FROM intraday_prices WHERE Symbol = ? ORDER BY Datetime DESC LIMIT ?",
            [symbol, limit],
        )
        return df.to_dicts()

    @app.get("/volatility")
    def volatility(symbol: str = Query(...), window: int = 30) -> list[dict[str, Any]]:
        df = _read_df(
            app.state.db,
            "SELECT * FROM intraday_prices WHERE Symbol = ? ORDER BY Datetime",
            [symbol],
        )
        if df.is_empty():
            raise HTTPException(status_code=404, detail=f"no data for {symbol}")
        out = VolatilityAnalyzer(df).calculate_realized_volatility(window_minutes=window)
        return out.select(["Datetime", "Symbol", "Close", "realized_vol"]).to_dicts()

    @app.get("/futures")
    def futures(front: str = Query(...), back: str = Query(...)) -> list[dict[str, Any]]:
        df = _read_df(
            app.state.db,
            "SELECT * FROM intraday_prices WHERE Symbol IN (?, ?) ORDER BY Datetime",
            [front, back],
        )
        if df.is_empty():
            raise HTTPException(status_code=404, detail="no data for the requested symbols")
        out = FuturesAnalyzer(df).calculate_term_structure(front, back)
        return out.select(["Datetime", "spread", "spread_pct"]).to_dicts()

    @app.get("/charts/price/{symbol}", response_class=HTMLResponse)
    def price_chart(symbol: str) -> str:
        df = _read_df(
            app.state.db,
            "SELECT * FROM intraday_prices WHERE Symbol = ? ORDER BY Datetime",
            [symbol],
        )
        if df.is_empty():
            raise HTTPException(status_code=404, detail=f"no data for {symbol}")
        fig = MarketVisualizer(df).plot_price_quality(symbol)
        return str(fig.to_html(include_plotlyjs="cdn"))

    return app


app = create_app()
