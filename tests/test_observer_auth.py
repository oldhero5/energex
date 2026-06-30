"""RBAC: every endpoint admits exactly the roles it should; the API trusts only the verified JWT."""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-jwt-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OBSERVER_JWT_SECRET", SECRET)
    monkeypatch.setenv("OBSERVER_CORS_ORIGINS", "http://localhost:3000")
    from energex.observer.app import create_app

    return TestClient(create_app())


def _token(role: str | None) -> dict:
    claims = {"sub": "u1", "exp": int(time.time()) + 3600, "aud": "authenticated"}
    if role is not None:
        claims["user_role"] = role
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def test_healthz_is_open(client):
    assert client.get("/healthz").status_code == 200


def test_me_requires_a_valid_token(client):
    assert client.get("/me").status_code == 401  # no token
    bad = {"Authorization": "Bearer " + jwt.encode({"sub": "u1"}, "wrong", algorithm="HS256")}
    assert client.get("/me", headers=bad).status_code == 401  # bad signature


@pytest.mark.parametrize("role,code", [("viewer", 200), ("operator", 200), ("admin", 200)])
def test_me_allows_any_authenticated_role(client, role, code):
    r = client.get("/me", headers=_token(role))
    assert r.status_code == code and r.json()["role"] == role


@pytest.mark.parametrize(
    "role,code", [(None, 403), ("viewer", 403), ("operator", 403), ("admin", 200)]
)
def test_admin_ping_requires_admin(client, role, code):
    assert client.get("/admin/ping", headers=_token(role)).status_code == code
