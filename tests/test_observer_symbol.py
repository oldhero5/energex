"""Per-symbol detail endpoints: /series (point-in-time), /schema, /vintages."""

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


def _frame(value, vt="2026-06-01"):
    idx = pd.DatetimeIndex([pd.Timestamp(vt)], name="Datetime")
    return pd.DataFrame(
        {
            "instrument_id": ["ERCOT.LOAD"],
            "valid_time": [pd.Timestamp(vt, tz="UTC")],
            "value": [value],
        },
        index=idx,
    )


def test_series_point_in_time(observer_client, observer_arctic):
    lib = observer_arctic["power.load"]
    storage.commit_vintage(
        lib,
        "erco",
        _frame(40000.0),
        as_of=dt.datetime(2026, 6, 2, tzinfo=dt.timezone.utc),
        source="ercot",
        source_url="x",
        fetched_at=dt.datetime(2026, 6, 2, tzinfo=dt.timezone.utc),
        mode="bitemporal_merge",
    )
    storage.commit_vintage(
        lib,
        "erco",
        _frame(41000.0),
        as_of=dt.datetime(2026, 6, 5, tzinfo=dt.timezone.utc),
        source="ercot",
        source_url="x",
        fetched_at=dt.datetime(2026, 6, 5, tzinfo=dt.timezone.utc),
        mode="bitemporal_merge",
    )
    # as_of between the two commits -> sees the first (40000), not the later revision
    r = observer_client.get(
        "/symbol/power.load/erco/series", params={"as_of": "2026-06-03T00:00:00Z"}
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows[-1]["value"] == 40000.0
    # latest (no as_of) -> sees the revision
    r2 = observer_client.get("/symbol/power.load/erco/series")
    assert r2.json()["rows"][-1]["value"] == 41000.0


def test_series_requires_auth(observer_arctic, monkeypatch):
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    from energex.observer.app import create_app

    anon = TestClient(create_app())
    assert anon.get("/symbol/power.load/erco/series").status_code == 401


def test_series_unknown_library_returns_404(observer_client):
    r = observer_client.get("/symbol/no.such.lib/erco/series")
    assert r.status_code == 404


def test_schema_known_library(observer_client):
    r = observer_client.get("/symbol/power.load/erco/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["schema_name"] == "ERCOT_LOAD"
    col_names = [c["name"] for c in body["columns"]]
    assert "value" in col_names


def test_schema_unknown_library_returns_null(observer_client):
    # unknown library -> schema_name is None
    r = observer_client.get("/symbol/no.such.lib/erco/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["schema_name"] is None
    assert body["columns"] == []


def test_vintages_seeded_symbol(observer_client, observer_arctic):
    lib = observer_arctic["power.load"]
    storage.commit_vintage(
        lib,
        "erco_vt",
        _frame(99.0),
        as_of=dt.datetime(2026, 6, 10, tzinfo=dt.timezone.utc),
        source="ercot",
        source_url="x",
        fetched_at=dt.datetime(2026, 6, 10, tzinfo=dt.timezone.utc),
        mode="bitemporal_merge",
    )
    r = observer_client.get("/symbol/power.load/erco_vt/vintages")
    assert r.status_code == 200
    body = r.json()
    assert len(body["vintages"]) == 1


def test_vintages_degenerate_symbol_returns_empty(observer_client, observer_arctic):
    """A symbol with no vintage sidecar (degenerate) returns an empty list."""
    lib = observer_arctic["power.load"]
    # write_bars requires a degenerate mode; use lib.write directly for a bare symbol
    lib.write(
        "bare_sym",
        _frame(1.0),
    )
    r = observer_client.get("/symbol/power.load/bare_sym/vintages")
    assert r.status_code == 200
    assert r.json()["vintages"] == []
