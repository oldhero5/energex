from __future__ import annotations

import logging

from fastapi import APIRouter

from energex.observer.arctic import VINTAGE_SUFFIX, get_arctic
from energex.observer.auth import Role, require_role

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/catalog")
def catalog(_claims: dict = require_role(Role.viewer)) -> dict:  # noqa: B008
    ac = get_arctic()
    out = []
    for name in sorted(ac.list_libraries()):
        lib = ac[name]
        syms = [s for s in lib.list_symbols() if not s.endswith(VINTAGE_SUFFIX)]
        rows = 0
        unreadable = 0
        for s in syms:
            try:
                rows += len(lib.read(s).data)
            except Exception:
                logger.warning(
                    "catalog: could not read symbol %r in library %r — skipping", s, name
                )
                unreadable += 1
        out.append({"name": name, "symbols": len(syms), "rows": rows, "unreadable": unreadable})
    return {"libraries": out}
