"""4V health layer: per-symbol freshness + metrics overview + /metrics/* endpoints."""

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


def _f(vt):
    idx = pd.DatetimeIndex([pd.Timestamp(vt)], name="Datetime")
    return pd.DataFrame(
        {
            "instrument_id": ["ERCOT.LOAD"],
            "valid_time": [pd.Timestamp(vt, tz="UTC")],
            "value": [40000.0],
        },
        index=idx,
    )


@pytest.fixture
def metrics_client(observer_arctic, monkeypatch):
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    monkeypatch.setenv("OBSERVER_CORS_ORIGINS", "")
    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    from energex.observer.app import create_app

    return TestClient(create_app())


# ── unit-level health tests ────────────────────────────────────────────────────


def test_health_flags_stale(observer_arctic):
    lib = observer_arctic["power.load"]
    now = dt.datetime.now(dt.timezone.utc)
    storage.commit_vintage(
        lib,
        "fresh",
        _f(now.date().isoformat()),
        as_of=now,
        source="e",
        source_url="x",
        fetched_at=now,
        mode="bitemporal_merge",
    )
    storage.commit_vintage(
        lib,
        "stale",
        _f("2025-01-01"),
        as_of=now,
        source="e",
        source_url="x",
        fetched_at=now,
        mode="bitemporal_merge",
    )
    # Clear cache so we get fresh reads.
    from energex.observer import health

    health._cache.clear()
    assert health.health_row("power.load", "fresh")["freshness_status"] == "ok"
    assert health.health_row("power.load", "stale")["freshness_status"] == "stale"


def test_health_cache_returns_same_object(observer_arctic):
    """Within TTL, the same dict object is returned without re-reading the store."""
    lib = observer_arctic["power.load"]
    now = dt.datetime.now(dt.timezone.utc)
    storage.commit_vintage(
        lib,
        "cached_sym",
        _f(now.date().isoformat()),
        as_of=now,
        source="e",
        source_url="x",
        fetched_at=now,
        mode="bitemporal_merge",
    )
    from energex.observer import health

    health._cache.clear()
    row1 = health.health_row("power.load", "cached_sym")
    row2 = health.health_row("power.load", "cached_sym")
    assert row1 is row2


def test_health_error_for_missing_symbol(observer_arctic):
    """A symbol that has never been written should return freshness_status='error'."""
    from energex.observer import health

    health._cache.clear()
    row = health.health_row("power.load", "does_not_exist")
    assert row["freshness_status"] == "error"
    assert row["latest_valid_time"] is None


# ── freshness mirror cross-check ───────────────────────────────────────────────


def test_freshness_mirror_matches_importable_constants():
    """Guard against the in-module mirror silently drifting from schemas.py constants."""
    from energex.core.schemas import _EIA_FRESHNESS_DAYS, _FRED_FRESHNESS_DAYS
    from energex.observer.health import _FRESHNESS_DAYS

    assert _FRESHNESS_DAYS["EIA_GAS_STORAGE"] == _EIA_FRESHNESS_DAYS
    assert _FRESHNESS_DAYS["EIA_PETROLEUM"] == _EIA_FRESHNESS_DAYS
    assert _FRESHNESS_DAYS["FRED_SPOT"] == _FRED_FRESHNESS_DAYS


# ── metrics.overview() unit ────────────────────────────────────────────────────


def test_overview_counts(observer_arctic):
    from energex.observer import health, metrics

    health._cache.clear()
    ov = metrics.overview()
    assert ov["volume"]["libraries"] >= 1
    assert set(ov.keys()) == {"volume", "velocity", "variety", "veracity"}
    # velocity keys present
    assert {"ok", "stale", "error"} == set(ov["velocity"].keys())
    # veracity key
    assert "broken" in ov["veracity"]


def test_health_rows_shape(observer_arctic):
    lib = observer_arctic["power.load"]
    now = dt.datetime.now(dt.timezone.utc)
    storage.commit_vintage(
        lib,
        "hr_sym",
        _f(now.date().isoformat()),
        as_of=now,
        source="e",
        source_url="x",
        fetched_at=now,
        mode="bitemporal_merge",
    )
    from energex.observer import health, metrics

    health._cache.clear()
    rows = metrics.health_rows()
    assert len(rows) >= 1
    row = next(r for r in rows if r["symbol"] == "hr_sym")
    assert row["library"] == "power.load"
    assert row["freshness_status"] in ("ok", "stale", "error")


# ── HTTP endpoint tests ────────────────────────────────────────────────────────


def test_overview_endpoint_viewer_200(metrics_client, observer_arctic):
    from energex.observer import health

    health._cache.clear()
    r = metrics_client.get("/metrics/overview", headers=_hdr("viewer"))
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"volume", "velocity", "variety", "veracity"}


def test_overview_endpoint_anon_401(observer_arctic, monkeypatch):
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    monkeypatch.setenv("OBSERVER_CORS_ORIGINS", "")
    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    from energex.observer.app import create_app

    anon = TestClient(create_app())
    assert anon.get("/metrics/overview").status_code == 401


def test_health_endpoint_viewer_200(metrics_client, observer_arctic):
    from energex.observer import health

    health._cache.clear()
    r = metrics_client.get("/metrics/health", headers=_hdr("viewer"))
    assert r.status_code == 200
    assert "rows" in r.json()


def test_health_endpoint_anon_401(observer_arctic, monkeypatch):
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    monkeypatch.setenv("OBSERVER_CORS_ORIGINS", "")
    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    from energex.observer.app import create_app

    anon = TestClient(create_app())
    assert anon.get("/metrics/health").status_code == 401
