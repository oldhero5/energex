"""Tests for the read-only Dagster GraphQL client.

The live schema (Dagster 1.13.9) differs from what the brief assumed:
- assetCheckExecutions requires assetKey+checkName (NON_NULL), returns a list directly (no .nodes).
- MetadataEntry is an interface; concrete types expose intValue/floatValue/text, not a generic `value`.
- schedulesOrError requires repositorySelector (NON_NULL).

The client instead uses:
- assetNodes with embedded assetChecksOrError.checks.executionForLatestMaterialization
- runsOrError (unchanged)
- workspaceOrError to collect schedules without needing repositorySelector

All tests mock httpx.Client.post so they run fully offline.
"""

from __future__ import annotations

import httpx

from energex.observer import dagster_client


def _fake_post(payload):
    def _post(self, url, json=None, **kw):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    return _post


# --- realistic payload shape (live Dagster 1.13.9 schema) ---

_HEALTHY_PAYLOAD = {
    "data": {
        "assetNodes": [
            {
                "assetKey": {"path": ["ercot_load"]},
                "assetChecksOrError": {
                    "__typename": "AssetChecks",
                    "checks": [
                        {
                            "name": "ercot_load_pass_quality_gate",
                            "executionForLatestMaterialization": {
                                "runId": "r1",
                                "status": "SUCCEEDED",
                                "timestamp": 1.0,
                                "evaluation": {
                                    "metadataEntries": [
                                        {"label": "rows", "intValue": 42},
                                        {"label": "symbols", "intValue": 5},
                                    ]
                                },
                            },
                        }
                    ],
                },
            },
            {
                "assetKey": {"path": ["eia930_region"]},
                "assetChecksOrError": {
                    "__typename": "AssetChecks",
                    "checks": [
                        {
                            "name": "eia930_region_pass_quality_gate",
                            "executionForLatestMaterialization": {
                                "runId": "r2",
                                "status": "EXECUTION_FAILED",
                                "timestamp": 2.0,
                                "evaluation": None,
                            },
                        }
                    ],
                },
            },
            # asset with no checks — must not crash
            {
                "assetKey": {"path": ["intraday_futures_bars"]},
                "assetChecksOrError": {
                    "__typename": "AssetChecks",
                    "checks": [],
                },
            },
        ],
        "runsOrError": {
            "results": [
                {
                    "id": "r1",
                    "status": "SUCCESS",
                    "startTime": 1.0,
                    "endTime": 2.0,
                    "assetSelection": None,
                }
            ]
        },
        "workspaceOrError": {
            "__typename": "Workspace",
            "locationEntries": [
                {
                    "locationOrLoadError": {
                        "__typename": "RepositoryLocation",
                        "repositories": [
                            {
                                "schedules": [
                                    {
                                        "name": "ercot_load_schedule",
                                        "scheduleState": {"status": "RUNNING"},
                                    }
                                ]
                            }
                        ],
                    }
                }
            ],
        },
    }
}


def test_get_pipeline_health_parses_checks(monkeypatch):
    monkeypatch.setattr(httpx.Client, "post", _fake_post(_HEALTHY_PAYLOAD))
    dagster_client._CACHE.clear()

    health = dagster_client.get_pipeline_health()

    assert health["available"] is True

    chk = next(c for c in health["checks"] if c["name"] == "ercot_load_pass_quality_gate")
    assert chk["passed"] is True
    assert chk["asset"] == "ercot_load"
    assert chk["metadata"]["rows"] == 42

    failed_chk = next(c for c in health["checks"] if c["name"] == "eia930_region_pass_quality_gate")
    assert failed_chk["passed"] is False


def test_get_pipeline_health_parses_runs(monkeypatch):
    monkeypatch.setattr(httpx.Client, "post", _fake_post(_HEALTHY_PAYLOAD))
    dagster_client._CACHE.clear()

    health = dagster_client.get_pipeline_health()

    assert len(health["runs"]) == 1
    assert health["runs"][0]["id"] == "r1"
    assert health["runs"][0]["status"] == "SUCCESS"


def test_get_pipeline_health_parses_schedules(monkeypatch):
    monkeypatch.setattr(httpx.Client, "post", _fake_post(_HEALTHY_PAYLOAD))
    dagster_client._CACHE.clear()

    health = dagster_client.get_pipeline_health()

    assert len(health["schedules"]) == 1
    assert health["schedules"][0]["name"] == "ercot_load_schedule"
    assert health["schedules"][0]["status"] == "RUNNING"


def test_get_pipeline_health_degrades_when_dagster_down(monkeypatch):
    def _boom(self, *a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.Client, "post", _boom)
    dagster_client._CACHE.clear()

    health = dagster_client.get_pipeline_health()

    assert health["available"] is False
    assert health["checks"] == []
    assert health["runs"] == []
    assert health["schedules"] == []
    assert health["error"]


def test_get_pipeline_health_degrades_on_http_error(monkeypatch):
    def _bad(self, url, json=None, **kw):
        return httpx.Response(500, text="Internal Server Error", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", _bad)
    dagster_client._CACHE.clear()

    health = dagster_client.get_pipeline_health()

    assert health["available"] is False
    assert health["error"]


def test_get_pipeline_health_degrades_on_missing_fields(monkeypatch):
    """Partial/empty payload must not KeyError — degrades to empty lists."""
    monkeypatch.setattr(httpx.Client, "post", _fake_post({"data": {}}))
    dagster_client._CACHE.clear()

    health = dagster_client.get_pipeline_health()

    assert health["available"] is True
    assert health["checks"] == []
    assert health["runs"] == []
    assert health["schedules"] == []
    assert health["error"] is None


def test_get_pipeline_health_skips_asset_nodes_without_checks(monkeypatch):
    """assetNodes with no checks must produce zero check entries, not crash."""
    monkeypatch.setattr(httpx.Client, "post", _fake_post(_HEALTHY_PAYLOAD))
    dagster_client._CACHE.clear()

    health = dagster_client.get_pipeline_health()

    # intraday_futures_bars has empty checks list — confirm it contributed nothing
    check_assets = {c["asset"] for c in health["checks"]}
    assert "intraday_futures_bars" not in check_assets


def test_dagster_client_import_is_safe():
    """Importing dagster_client must not raise even without env vars set."""
    import importlib

    importlib.reload(dagster_client)
    assert hasattr(dagster_client, "get_pipeline_health")


def test_cache_returns_stale_result_within_ttl(monkeypatch):
    """Second call within TTL must be served from cache without hitting the network."""
    monkeypatch.setattr(httpx.Client, "post", _fake_post(_HEALTHY_PAYLOAD))
    dagster_client._CACHE.clear()

    first = dagster_client.get_pipeline_health()
    assert first["available"] is True

    def _boom(self, *a, **k):
        raise httpx.ConnectError("must not be called within TTL")

    monkeypatch.setattr(httpx.Client, "post", _boom)
    second = dagster_client.get_pipeline_health()
    assert second["available"] is True  # served from cache, no raise


def test_parse_data_null_degrades_safely(monkeypatch):
    """A {data: null, errors: [...]} response must not raise and returns normalized shape."""
    payload = {"data": None, "errors": [{"message": "something failed"}]}
    monkeypatch.setattr(httpx.Client, "post", _fake_post(payload))
    dagster_client._CACHE.clear()

    health = dagster_client.get_pipeline_health()

    assert health["available"] is True
    assert health["checks"] == []
    assert health["runs"] == []
    assert health["schedules"] == []
    assert health["error"] is None


def test_config_accepts_missing_supabase_vars(monkeypatch):
    """ObserverSettings must construct without SUPABASE_URL / SUPABASE_SERVICE_KEY."""
    monkeypatch.setenv("OBSERVER_JWT_SECRET", "test-secret")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)

    from energex.observer.config import ObserverSettings

    s = ObserverSettings()
    assert s.supabase_url is None
    assert s.supabase_service_key is None
    assert s.dagster_graphql_url == "http://dagster-webserver:3000/graphql"
