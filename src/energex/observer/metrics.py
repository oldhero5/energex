"""4V metrics: volume, velocity, variety, veracity over the full catalog."""

from __future__ import annotations

from energex.observer import health, metadata


def health_rows() -> list[dict]:
    rows = []
    for lib in metadata.list_catalog()["libraries"]:
        for s in lib["symbols"]:
            r = health.health_row(lib["name"], s["symbol"])
            rows.append({"library": lib["name"], **r, "schema_name": s["schema_name"]})
    return rows


def overview() -> dict:
    cat = metadata.list_catalog()
    rows = health_rows()
    schemas_seen = {
        s["schema_name"] for lib in cat["libraries"] for s in lib["symbols"] if s["schema_name"]
    }
    modes = {lib["mode"] for lib in cat["libraries"]}
    stale = [r for r in rows if r["freshness_status"] in ("stale", "error")]
    return {
        "volume": {
            "libraries": len(cat["libraries"]),
            "symbols": sum(len(lib["symbols"]) for lib in cat["libraries"]),
            "rows": sum((s["row_count"] or 0) for lib in cat["libraries"] for s in lib["symbols"]),
        },
        "velocity": {
            "ok": sum(1 for r in rows if r["freshness_status"] == "ok"),
            "stale": sum(1 for r in rows if r["freshness_status"] == "stale"),
            "error": sum(1 for r in rows if r["freshness_status"] == "error"),
        },
        "variety": {
            "schemas": len(schemas_seen),
            "revision_modes": sorted(modes),
        },
        "veracity": {
            "broken": len(stale),
            "broken_symbols": [{"library": r["library"], "symbol": r["symbol"]} for r in stale][
                :50
            ],
        },
    }
