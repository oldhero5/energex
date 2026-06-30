from __future__ import annotations

from fastapi import APIRouter

from energex.observer.arctic import VINTAGE_SUFFIX, get_arctic
from energex.observer.auth import Role, require_role

router = APIRouter()


@router.get("/catalog")
def catalog(_claims: dict = require_role(Role.viewer)) -> dict:  # noqa: B008
    ac = get_arctic()
    out = []
    for name in sorted(ac.list_libraries()):
        lib = ac[name]
        syms = [s for s in lib.list_symbols() if not s.endswith(VINTAGE_SUFFIX)]
        rows = sum(len(lib.read(s).data) for s in syms)
        out.append({"name": name, "symbols": len(syms), "rows": rows})
    return {"libraries": out}
