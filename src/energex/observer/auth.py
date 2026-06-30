"""RBAC over the Supabase JWT. Role comes from the verified `user_role` claim (injected by a
Supabase custom-access-token hook); the API NEVER trusts an unverified client value."""

from __future__ import annotations

import enum

import jwt
from fastapi import Depends, Header, HTTPException

from energex.observer.config import ObserverSettings


class Role(str, enum.Enum):
    viewer = "viewer"
    operator = "operator"
    admin = "admin"


_ORDER = {Role.viewer: 0, Role.operator: 1, Role.admin: 2}


def _settings() -> ObserverSettings:
    return ObserverSettings()  # cheap; reads env each call (test-friendly)


def _verified_claims(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    s = _settings()
    try:
        return jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=s.jwt_audience,
            options={"require": ["exp", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc


def require_role(min_role: Role):
    """FastAPI dependency: 401 if unauthenticated, 403 if the verified role is below min_role.
    Returns the claims dict (with a normalized `role`) for the handler."""

    def _dep(authorization: str | None = Header(default=None)) -> dict:
        claims = _verified_claims(authorization)
        raw = claims.get("user_role")
        try:
            role = Role(raw)
        except ValueError:
            raise HTTPException(status_code=403, detail="no role assigned") from None
        if _ORDER[role] < _ORDER[min_role]:
            raise HTTPException(status_code=403, detail=f"requires {min_role.value}")
        claims["role"] = role.value
        return claims

    return Depends(_dep)
