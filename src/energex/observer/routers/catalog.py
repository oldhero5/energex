from __future__ import annotations

from fastapi import APIRouter

from energex.observer import metadata
from energex.observer.auth import Role, require_role

router = APIRouter()


@router.get("/catalog")
def catalog(_claims: dict = require_role(Role.viewer)) -> dict:  # noqa: B008
    return metadata.list_catalog()
