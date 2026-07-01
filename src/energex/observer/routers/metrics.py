"""GET /metrics/overview and GET /metrics/health — viewer-gated 4V metrics."""

from __future__ import annotations

from fastapi import APIRouter

from energex.observer import metrics
from energex.observer.auth import Role, require_role

router = APIRouter(prefix="/metrics")


@router.get("/overview")
def overview(_c: dict = require_role(Role.viewer)) -> dict:  # noqa: B008
    return metrics.overview()


@router.get("/health")
def health_endpoint(_c: dict = require_role(Role.viewer)) -> dict:  # noqa: B008
    return {"rows": metrics.health_rows()}
