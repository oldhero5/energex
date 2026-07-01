"""Read-only Dagster GraphQL client for the Quality board. Sync httpx (routers are sync).

Resilient: any transport/parse error -> {available: False} (the board degrades, never 500s).

Query design confirmed against the running dagster-webserver (Dagster 1.13.9) during the task-1
schema spike. Key deviations from the brief's assumed schema:

  - assetCheckExecutions(assetKey, checkName) is per-check, requires NON_NULL args — unusable for
    a bulk scan. Instead we query assetNodes with embedded
    assetChecksOrError.checks.executionForLatestMaterialization (one round-trip, all checks).
  - MetadataEntry is an interface; concrete subtypes expose intValue/floatValue/text rather than a
    generic `value` field.
  - schedulesOrError requires repositorySelector (NON_NULL). Instead we use workspaceOrError and
    collect schedules from embedded repositories.
  - Check status enum values: SUCCEEDED / EXECUTION_FAILED / SKIPPED / FAILED (not PASSED).
    passed = (status == "SUCCEEDED").
"""

from __future__ import annotations

import os
import time

import httpx

# Single query that fetches all three data categories in one round-trip.
_CHECKS_QUERY = """
query ObserverChecks {
  assetNodes(loadMaterializations: false) {
    assetKey { path }
    assetChecksOrError {
      __typename
      ... on AssetChecks {
        checks {
          name
          executionForLatestMaterialization {
            runId status timestamp
            evaluation {
              metadataEntries {
                label
                ... on IntMetadataEntry   { intValue }
                ... on FloatMetadataEntry { floatValue }
                ... on TextMetadataEntry  { text }
              }
            }
          }
        }
      }
    }
  }
  runsOrError(limit: 100) {
    ... on Runs {
      results { id status startTime endTime assetSelection { path } }
    }
  }
  workspaceOrError {
    ... on Workspace {
      locationEntries {
        locationOrLoadError {
          ... on RepositoryLocation {
            repositories {
              schedules { name scheduleState { status } }
            }
          }
        }
      }
    }
  }
}
"""

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 300  # seconds; override with OBSERVER_DAGSTER_TTL_SECONDS env var


def _dagster_url() -> str:
    """Return the Dagster GraphQL URL from env (or the default) without requiring jwt_secret."""
    return os.environ.get("DAGSTER_GRAPHQL_URL", "http://dagster-webserver:3000/graphql")


def _query(url: str) -> dict:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(url, json={"query": _CHECKS_QUERY})
        resp.raise_for_status()
        return resp.json()


def _metadata_value(entry: dict) -> object:
    """Extract the concrete value from a MetadataEntry inline-fragment result."""
    if "intValue" in entry:
        return entry["intValue"]
    if "floatValue" in entry:
        return entry["floatValue"]
    if "text" in entry:
        return entry["text"]
    return None


def _parse(raw: dict) -> dict:
    data = (raw or {}).get("data") or {}

    # --- checks (from assetNodes) ---
    checks = []
    for node in data.get("assetNodes") or []:
        asset_path = (node.get("assetKey") or {}).get("path") or []
        asset_name = asset_path[-1] if asset_path else None
        checks_or_err = node.get("assetChecksOrError") or {}
        if checks_or_err.get("__typename") != "AssetChecks":
            continue
        for chk in checks_or_err.get("checks") or []:
            exec_ = chk.get("executionForLatestMaterialization")
            if exec_ is None:
                checks.append(
                    {
                        "name": chk.get("name"),
                        "asset": asset_name,
                        "passed": None,
                        "status": None,
                        "timestamp": None,
                        "metadata": {},
                        "last_run_status": None,
                    }
                )
                continue
            status = exec_.get("status")
            metadata_entries = (exec_.get("evaluation") or {}).get("metadataEntries") or []
            checks.append(
                {
                    "name": chk.get("name"),
                    "asset": asset_name,
                    "passed": status == "SUCCEEDED",
                    "status": status,
                    "timestamp": exec_.get("timestamp"),
                    "metadata": {
                        e["label"]: _metadata_value(e) for e in metadata_entries if "label" in e
                    },
                    "last_run_status": status,
                }
            )

    # --- runs ---
    runs_data = data.get("runsOrError") or {}
    runs = [
        {
            "id": r.get("id"),
            "status": r.get("status"),
            "startTime": r.get("startTime"),
            "endTime": r.get("endTime"),
            "assets": [".".join(a.get("path") or []) for a in (r.get("assetSelection") or [])],
        }
        for r in (runs_data.get("results") or [])
    ]

    # --- schedules (collected from workspace → locations → repos) ---
    schedules = []
    workspace = data.get("workspaceOrError") or {}
    for entry in workspace.get("locationEntries") or []:
        loc = entry.get("locationOrLoadError") or {}
        for repo in loc.get("repositories") or []:
            for sched in repo.get("schedules") or []:
                schedules.append(
                    {
                        "name": sched.get("name"),
                        "status": (sched.get("scheduleState") or {}).get("status"),
                        "last_tick": None,
                    }
                )

    return {
        "available": True,
        "checks": checks,
        "runs": runs,
        "schedules": schedules,
        "error": None,
    }


def get_pipeline_health() -> dict:
    """Return pipeline health snapshot. Never raises — any failure → available=False."""
    ttl = int(os.environ.get("OBSERVER_DAGSTER_TTL_SECONDS", _TTL))
    hit = _CACHE.get("health")
    if hit and (time.monotonic() - hit[0]) < ttl:
        return hit[1]
    try:
        result = _parse(_query(_dagster_url()))
    except Exception as exc:  # transport, HTTP status, or parse — degrade, never raise
        result = {"available": False, "checks": [], "runs": [], "schedules": [], "error": str(exc)}
    _CACHE["health"] = (time.monotonic(), result)
    return result
