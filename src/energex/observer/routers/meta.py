from __future__ import annotations

from fastapi import APIRouter

from energex.observer.auth import Role, require_role

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    # Open probe: no require_role. The Docker healthcheck (every observer route else needs a
    # Supabase JWT) hits this, so it must stay unauthenticated.
    return {"status": "ok"}


@router.get("/me")
def me(claims: dict = require_role(Role.viewer)) -> dict:  # noqa: B008
    return {"user": claims.get("sub"), "role": claims["role"]}


@router.get("/admin/ping")
def admin_ping(claims: dict = require_role(Role.admin)) -> dict:  # noqa: B008
    return {"ok": True}
