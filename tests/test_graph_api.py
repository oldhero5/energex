"""S2 /graph endpoints: lazy driver, 503 degradation, catalog + related queries."""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from energex.core import graph as core_graph  # noqa: E402
from energex.core.exceptions import GraphError  # noqa: E402
from energex.service.readapi import create_app  # noqa: E402


class FakeDriver:
    def __init__(self, results=None):
        self.calls = []
        self._results = results or {}
        self.closed = False

    def execute_query(self, query_, parameters_=None, database_=None, **_kw):
        params = dict(parameters_ or {})
        self.calls.append((query_, params, database_))
        for needle, records in self._results.items():
            if needle in query_:
                if callable(records):  # parameter-sensitive results
                    records = records(params)
                return SimpleNamespace(records=records, summary=None, keys=[])
        return SimpleNamespace(records=[], summary=None, keys=[])

    def close(self):
        self.closed = True


@pytest.fixture
def client(monkeypatch, arctic_uri):
    monkeypatch.setenv("ENERGEX_ARCTIC_URI", arctic_uri)
    return TestClient(create_app())


def _install_driver(monkeypatch, driver):
    monkeypatch.setattr(core_graph, "create_driver", lambda cfg: driver)


def test_graph_unavailable_returns_503_and_healthz_false(monkeypatch, client):
    def boom(cfg):
        raise GraphError("Neo4j connection failed: ServiceUnavailable")

    monkeypatch.setattr(core_graph, "create_driver", boom)
    with client as c:
        assert c.get("/healthz").json()["graph"] is False
        response = c.get("/graph/entities")
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"]


def test_graph_entities_lists_catalog(monkeypatch, client):
    records = [
        {
            "label": "SettlementPoint",
            "key": "HB_NORTH",
            "properties": {"code": "HB_NORTH", "kind": "hub"},
        }
    ]
    _install_driver(monkeypatch, FakeDriver(results={"MATCH": records}))
    with client as c:
        response = c.get("/graph/entities", params={"label": "SettlementPoint"})
        assert response.status_code == 200
        assert response.json()[0]["key"] == "HB_NORTH"
        # after a successful graph call, healthz reports the graph as up
        assert c.get("/healthz").json()["graph"] is True


def test_graph_entities_unknown_label_404(monkeypatch, client):
    _install_driver(monkeypatch, FakeDriver())
    with client as c:
        assert c.get("/graph/entities", params={"label": "Nope"}).status_code == 404


def test_graph_related_contract(monkeypatch, client):
    def exists(params):
        if params["iid"] == "ERCOT.SPP.HB_NORTH":
            return [{"instrument_id": "ERCOT.SPP.HB_NORTH"}]
        return []

    related = [{"label": "SettlementPoint", "key": "HB_NORTH", "properties": {"code": "HB_NORTH"}}]
    _install_driver(
        monkeypatch, FakeDriver(results={"RETURN i.instrument_id": exists, "DISTINCT": related})
    )
    with client as c:
        response = c.get(
            "/graph/related", params={"instrument_id": "ERCOT.SPP.HB_NORTH", "depth": 1}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["instrument_id"] == "ERCOT.SPP.HB_NORTH"
        assert body["related"][0]["key"] == "HB_NORTH"

        assert c.get("/graph/related", params={"instrument_id": "NOPE.X"}).status_code == 404
        assert (
            c.get(
                "/graph/related",
                params={"instrument_id": "ERCOT.SPP.HB_NORTH", "depth": 7},
            ).status_code
            == 422
        )


def test_driver_closed_on_shutdown(monkeypatch, client):
    driver = FakeDriver()
    _install_driver(monkeypatch, driver)
    with client as c:
        c.get("/graph/entities")
    assert driver.closed is True


def test_failed_connect_backs_off_without_reattempting(monkeypatch, client):
    calls = {"n": 0}

    def boom(cfg):
        calls["n"] += 1
        raise GraphError("Neo4j connection failed: ServiceUnavailable")

    monkeypatch.setattr(core_graph, "create_driver", boom)
    with client as c:
        assert c.get("/graph/entities").status_code == 503
        # within GRAPH_RETRY_SECONDS the second request fails fast: no new attempt
        assert c.get("/graph/entities").status_code == 503
    assert calls["n"] == 1


class BrokenQueryDriver(FakeDriver):
    """Connects fine, then every query blows up (e.g. neo4j died mid-flight)."""

    def execute_query(self, query_, parameters_=None, database_=None, **_kw):
        raise RuntimeError("bolt connection reset")


def test_query_time_failure_returns_503_on_both_endpoints(monkeypatch, client):
    _install_driver(monkeypatch, BrokenQueryDriver())
    with client as c:
        response = c.get("/graph/entities")
        assert response.status_code == 503
        response = c.get("/graph/related", params={"instrument_id": "FRED.WTI.SPOT"})
        assert response.status_code == 503
