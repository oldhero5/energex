"""/catalog lists libraries + per-library symbol/row counts from ArcticDB; viewer-gated."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import jwt
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from energex.core import storage

SECRET = "test-jwt-secret"


def _hdr(role="viewer"):
    t = jwt.encode(
        {"sub": "u1", "exp": int(time.time()) + 3600, "aud": "authenticated", "user_role": role},
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def client(arctic_store, arctic_uri, monkeypatch):
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    monkeypatch.setenv("OBSERVER_CORS_ORIGINS", "")
    monkeypatch.setenv("ENERGEX_ARCTIC_URI", arctic_uri)
    lib = arctic_store.create_library("power.lmp")
    storage.commit_vintage(
        lib,
        "hb_houston",
        pd.DataFrame(
            {
                "instrument_id": "ERCOT.SPP.HB_HOUSTON",
                "valid_time": [datetime(2026, 6, 26, tzinfo=timezone.utc)],
                "settlement_point": ["HB_HOUSTON"],
                "price": [42.5],
            }
        ),
        as_of=datetime(2026, 6, 27, tzinfo=timezone.utc),
        source="ercot",
        source_url="u",
        fetched_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
        mode="bitemporal_merge",
    )
    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    from energex.observer.app import create_app

    return TestClient(create_app())


def test_catalog_requires_viewer(client):
    assert client.get("/catalog").status_code == 401


def test_catalog_lists_libraries(client):
    body = client.get("/catalog", headers=_hdr()).json()
    libs = {x["name"]: x for x in body["libraries"]}
    assert "power.lmp" in libs
    assert libs["power.lmp"]["symbols"] == 1 and libs["power.lmp"]["rows"] == 1
