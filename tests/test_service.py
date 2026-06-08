"""Tests for the FastAPI service layer (R-SVC)."""

from datetime import datetime, timedelta, timezone

import polars as pl
import pytest
from fastapi.testclient import TestClient

from energex.database import EnergyDatabase
from energex.service.app import create_app
from energex.service.scheduler import INGEST_JOB_ID, build_scheduler


def _seed(db_path: str) -> int:
    base = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
    rows = []
    for sym, p0 in (("CL=F", 75.0), ("NG=F", 2.5)):
        for i in range(30):
            px = p0 + i * 0.1
            rows.append(
                {
                    "Datetime": base + timedelta(minutes=i),
                    "Symbol": sym,
                    "Open": px,
                    "High": px + 0.2,
                    "Low": px - 0.2,
                    "Close": px + 0.05,
                    "Volume": 1000 + i,
                }
            )
    db = EnergyDatabase(db_path)
    df = pl.DataFrame(rows)
    db.insert_intraday_data(df)
    db.conn.close()
    return df.height


@pytest.fixture
def client(tmp_db_path):
    total = _seed(tmp_db_path)
    app = create_app(db_path=tmp_db_path, start_scheduler=False)
    with TestClient(app) as c:
        c.seeded_rows = total  # type: ignore[attr-defined]
        yield c


def test_healthz_reports_ok_and_row_count(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["rows"] == client.seeded_rows
    assert body["latest"] is not None


def test_prices_endpoint_filters_by_symbol(client):
    r = client.get("/prices", params={"symbol": "CL=F", "limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 5
    assert all(row["Symbol"] == "CL=F" for row in data)


def test_volatility_endpoint_returns_realized_vol(client):
    r = client.get("/volatility", params={"symbol": "CL=F", "window": 5})
    assert r.status_code == 200
    data = r.json()
    assert data and "realized_vol" in data[0]


def test_volatility_unknown_symbol_404(client):
    r = client.get("/volatility", params={"symbol": "ZZ=F"})
    assert r.status_code == 404


def test_futures_endpoint_returns_spread(client):
    r = client.get("/futures", params={"front": "CL=F", "back": "NG=F"})
    assert r.status_code == 200
    data = r.json()
    assert data and "spread" in data[0]


def test_price_chart_returns_html(client):
    r = client.get("/charts/price/CL=F")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "plotly" in r.text.lower()


def test_scheduler_registers_ingest_job():
    scheduler = build_scheduler(lambda: None, cron="*/5 * * * *")
    try:
        assert scheduler.get_job(INGEST_JOB_ID) is not None
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def test_run_ingestion_upserts(monkeypatch, tmp_db_path):
    from energex.service import pipeline
    from energex.sources.yfinance_source import YFinanceDataSource

    fake = pl.DataFrame(
        {
            "Datetime": [datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)],
            "Symbol": ["CL=F"],
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Volume": [1],
        }
    )
    monkeypatch.setattr(YFinanceDataSource, "fetch_all", lambda self: fake)
    db = EnergyDatabase(tmp_db_path)
    n = pipeline.run_ingestion(db)
    count = db.conn.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    db.conn.close()
    assert n == 1
    assert count == 1


def test_sentiment_endpoint_returns_analysis(client, monkeypatch):
    from energex.analysis.market_sentiment import MarketSentimentAnalyzer

    monkeypatch.setattr(
        MarketSentimentAnalyzer,
        "analyze_headline",
        lambda self, title, summary=None: {
            "sentiment_score": 0.7,
            "confidence": 0.9,
            "impact_sector": "Oil",
            "trade_signal": "LONG",
            "key_factors": ["OPEC cuts"],
        },
    )
    r = client.get("/sentiment", params={"headline": "Oil prices rise"})
    assert r.status_code == 200
    body = r.json()
    assert body["sentiment"]["trade_signal"] == "LONG"
    assert "provider" in body and "llm_available" in body
