"""Veracity endpoint tests: /symbol/{library}/{symbol}/quality re-runs the pandera gate."""

from __future__ import annotations

import datetime as dt
import time

import jwt
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from energex.core import storage

SECRET = "test-jwt-secret"


def _make_token(role="viewer"):
    claims = {
        "sub": "u1",
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
        "user_role": role,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _hdr(role="viewer"):
    return {"Authorization": f"Bearer {_make_token(role)}"}


@pytest.fixture
def observer_client(observer_arctic, monkeypatch):
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    monkeypatch.setenv("OBSERVER_CORS_ORIGINS", "")
    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    from energex.observer.app import create_app

    client = TestClient(create_app())
    client.headers.update(_hdr("viewer"))
    return client


def _load_frame(value, vt):
    idx = pd.DatetimeIndex([pd.Timestamp(vt)], name="Datetime")
    return pd.DataFrame(
        {
            "instrument_id": ["ERCOT.LOAD"],
            "valid_time": [pd.Timestamp(vt, tz="UTC")],
            "value": [value],
        },
        index=idx,
    )


def test_symbol_quality_passes_for_fresh_inband(observer_arctic):
    lib = observer_arctic["power.load"]
    today = dt.datetime.now(dt.timezone.utc)
    storage.commit_vintage(
        lib,
        "fresh",
        _load_frame(40000.0, today.date().isoformat()),
        as_of=today,
        source="ercot",
        source_url="x",
        fetched_at=today,
        mode="bitemporal_merge",
    )
    from energex.observer import quality_service

    res = quality_service.symbol_quality("power.load", "fresh", as_of=None)
    assert res["passed"] is True
    assert res["schema_name"] == "ERCOT_LOAD"


def test_symbol_quality_fails_for_stale(observer_arctic):
    lib = observer_arctic["power.load"]
    old = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    storage.commit_vintage(
        lib,
        "stale",
        _load_frame(40000.0, "2025-01-01"),
        as_of=old,
        source="ercot",
        source_url="x",
        fetched_at=old,
        mode="bitemporal_merge",
    )
    from energex.observer import quality_service

    # validated against now() — the 2025-01-01 valid_time will be stale
    res = quality_service.symbol_quality("power.load", "stale", as_of=None)
    assert res["passed"] is False
    assert any("staler" in f["check"] for f in res["failures"])


def test_quality_endpoint_returns_200(observer_client, observer_arctic):
    lib = observer_arctic["power.load"]
    today = dt.datetime.now(dt.timezone.utc)
    storage.commit_vintage(
        lib,
        "ep_fresh",
        _load_frame(40000.0, today.date().isoformat()),
        as_of=today,
        source="ercot",
        source_url="x",
        fetched_at=today,
        mode="bitemporal_merge",
    )
    r = observer_client.get("/symbol/power.load/ep_fresh/quality")
    assert r.status_code == 200
    body = r.json()
    assert body["passed"] is True
    assert body["schema_name"] == "ERCOT_LOAD"


def test_quality_endpoint_requires_auth(observer_arctic, monkeypatch):
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    monkeypatch.setenv("OBSERVER_CORS_ORIGINS", "")
    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    from energex.observer.app import create_app

    anon = TestClient(create_app())
    assert anon.get("/symbol/power.load/x/quality").status_code == 401


def test_quality_unknown_library_returns_404(observer_client):
    r = observer_client.get("/symbol/no.such.lib/x/quality")
    assert r.status_code == 404


def _ohlcv_frame(symbol: str, n: int = 5) -> pd.DataFrame:
    base = pd.Timestamp("2026-01-02 14:30:00", tz="UTC")
    rows = []
    for i in range(n):
        vt = base + pd.Timedelta(minutes=i)
        px = 75.0 + i * 0.1
        rows.append(
            {
                "instrument_id": [symbol],
                "valid_time": [vt],
                "Open": [px],
                "High": [px + 0.2],
                "Low": [px - 0.2],
                "Close": [px + 0.05],
                "Volume": [1000 + i * 10],
            }
        )
    return pd.concat([pd.DataFrame(r) for r in rows], ignore_index=True)


def test_symbol_quality_ohlcv_anomalies_not_silent_noop(observer_arctic):
    """OHLCV anomaly path adapts instrument_id->Symbol; result is a real dict, not None."""
    observer_arctic.create_library("prices.intraday")
    lib = observer_arctic["prices.intraday"]
    fetched_at = dt.datetime.now(dt.timezone.utc)
    storage.write_bars(
        lib, "CL_FRONT", _ohlcv_frame("CME.CL.FRONT"), fetched_at=fetched_at, mode="degenerate"
    )

    from energex.observer import quality_service

    res = quality_service.symbol_quality("prices.intraday", "CL_FRONT", as_of=None)
    assert isinstance(res["anomalies"], dict), (
        f"expected dict, got: {res.get('anomalies_note', res['anomalies'])}"
    )
    assert "total_records" in res["anomalies"]
    assert res["anomalies"]["total_records"] == 5
