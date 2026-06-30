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
    assert libs["power.lmp"]["unreadable"] == 0


def test_catalog_resilient_to_bad_symbol(arctic_store, arctic_uri, monkeypatch):
    """One corrupt symbol must not 500 the whole /catalog response."""
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    monkeypatch.setenv("OBSERVER_CORS_ORIGINS", "")
    monkeypatch.setenv("ENERGEX_ARCTIC_URI", arctic_uri)

    lib = arctic_store.create_library("power.bad")
    for sym in ("good_sym", "bad_sym"):
        storage.commit_vintage(
            lib,
            sym,
            pd.DataFrame(
                {
                    "instrument_id": sym.upper(),
                    "valid_time": [datetime(2026, 6, 26, tzinfo=timezone.utc)],
                    "settlement_point": [sym.upper()],
                    "price": [1.0],
                }
            ),
            as_of=datetime(2026, 6, 27, tzinfo=timezone.utc),
            source="test",
            source_url="u",
            fetched_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
            mode="bitemporal_merge",
        )

    # Patch the catalog router so bad_sym raises during the request
    import energex.observer.routers.catalog as catalog_mod

    _orig_get_arctic = catalog_mod.get_arctic

    def _patched_get_arctic():
        ac = arctic_store

        class _PatchedArcticProxy:
            def list_libraries(self):
                return ac.list_libraries()

            def __getitem__(self, name):
                lib_obj = ac[name]
                if name == "power.bad":
                    _real_read = lib_obj.read

                    def _bad_read(sym, *args, **kwargs):
                        if sym == "bad_sym":
                            raise RuntimeError("simulated corrupt symbol")
                        return _real_read(sym, *args, **kwargs)

                    lib_obj.read = _bad_read
                return lib_obj

        return _PatchedArcticProxy()

    from energex.observer.arctic import get_arctic

    get_arctic.cache_clear()
    monkeypatch.setattr(catalog_mod, "get_arctic", _patched_get_arctic)

    from energex.observer.app import create_app

    resp = TestClient(create_app()).get("/catalog", headers=_hdr())
    assert resp.status_code == 200
    libs = {x["name"]: x for x in resp.json()["libraries"]}
    entry = libs["power.bad"]
    assert entry["symbols"] == 2
    assert entry["rows"] == 1  # only good_sym counted
    assert entry["unreadable"] >= 1
