"""sync_graph / create_driver / read queries against a duck-typed fake driver."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from energex.core import graph
from energex.core.config import Neo4jConfig
from energex.core.exceptions import GraphError

SYNCED_AT = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


class FakeDriver:
    def __init__(self, results=None, fail=False):
        self.calls: list[tuple[str, dict, str | None]] = []
        self._results = results or {}
        self._fail = fail

    def execute_query(self, query_, parameters_=None, database_=None, **_kw):
        if self._fail:
            raise RuntimeError("bolt://user:secret@host exploded")
        self.calls.append((query_, dict(parameters_ or {}), database_))
        for needle, records in self._results.items():
            if needle in query_:
                return SimpleNamespace(records=records, summary=None, keys=[])
        return SimpleNamespace(records=[], summary=None, keys=[])

    def close(self):
        pass


def _sync(driver):
    plan = graph.build_entity_graph()
    return graph.sync_graph(driver, plan, synced_at=SYNCED_AT)


def test_sync_runs_constraints_then_merges_and_counts():
    driver = FakeDriver()
    result = _sync(driver)
    queries = [q for q, _, _ in driver.calls]
    n_constraints = sum("CREATE CONSTRAINT" in q for q in queries)
    assert n_constraints == len(graph.KEY_PROPERTY)
    # constraints run before any MERGE batch
    first_merge = next(i for i, q in enumerate(queries) if "UNWIND" in q)
    assert all("CREATE CONSTRAINT" in q for q in queries[:first_merge])
    # every batch is an idempotent MERGE; nothing uses bare CREATE
    assert all("CREATE (" not in q for q in queries)
    assert result.nodes_by_label["SettlementPoint"] == 13
    assert result.edges_by_type["IN_MARKET"] == 13


def test_sync_stamps_first_and_last_seen():
    driver = FakeDriver()
    _sync(driver)
    merges = [(q, p) for q, p, _ in driver.calls if "UNWIND" in q]
    assert merges
    for q, params in merges:
        assert "ON CREATE SET" in q and "first_seen" in q and "last_seen" in q
        assert params["synced_at"] == SYNCED_AT


def test_sync_failure_is_wrapped_and_redacted():
    with pytest.raises(GraphError) as exc_info:
        _sync(FakeDriver(fail=True))
    assert "secret" not in str(exc_info.value)
    assert "RuntimeError" in str(exc_info.value)


def test_create_driver_without_neo4j_extra_raises_graph_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_neo4j(name, *args, **kwargs):
        if name == "neo4j" or name.startswith("neo4j."):
            raise ImportError("No module named 'neo4j'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_neo4j)
    with pytest.raises(GraphError, match="graph.*extra"):
        graph.create_driver(Neo4jConfig())


class FakeNeo4jDateTime:
    """Mimics neo4j.time.DateTime: exposes to_native() -> datetime."""

    def __init__(self, dt):
        self._dt = dt

    def to_native(self):
        return self._dt


def test_list_entities_validates_label_and_cleans_records():
    records = [
        {
            "label": "Instrument",
            "key": "FRED.WTI.SPOT",
            # exercise the real driver contract: temporal props arrive as
            # neo4j.time.DateTime-like objects, not python datetimes
            "properties": {
                "instrument_id": "FRED.WTI.SPOT",
                "first_seen": FakeNeo4jDateTime(SYNCED_AT),
            },
        }
    ]
    driver = FakeDriver(results={"MATCH": records})
    rows = graph.list_entities(driver, label="Instrument")
    assert rows[0]["key"] == "FRED.WTI.SPOT"
    assert rows[0]["properties"]["first_seen"] == SYNCED_AT.isoformat()
    with pytest.raises(GraphError, match="unknown label"):
        graph.list_entities(driver, label="DropAllTables")


def test_list_entities_cypher_shape_for_label_and_none():
    driver = FakeDriver()
    graph.list_entities(driver, label="Market")
    graph.list_entities(driver)  # label=None must match ALL nodes, not :None
    labelled, unlabelled = driver.calls[0][0], driver.calls[1][0]
    assert labelled.startswith("MATCH (n:Market)")
    assert unlabelled.startswith("MATCH (n)\n")
    assert "None" not in unlabelled


def test_redact_uri_strips_userinfo_with_and_without_scheme():
    assert graph._redact_uri("bolt://user:secret@host:7687") == "bolt://host:7687"
    assert graph._redact_uri("user:secret@host:7687") == "host:7687"
    assert graph._redact_uri("bolt://host:7687") == "bolt://host:7687"


def test_related_instruments_unknown_returns_none_and_depth_validated():
    driver = FakeDriver()  # no records -> instrument not found
    assert graph.related_instruments(driver, "NOPE.X") is None
    with pytest.raises(GraphError, match="depth"):
        graph.related_instruments(driver, "FRED.WTI.SPOT", depth=9)


def test_related_instruments_returns_cleaned_neighbors():
    exists = [{"instrument_id": "ERCOT.SPP.HB_NORTH"}]
    related = [
        {"label": "SettlementPoint", "key": "HB_NORTH", "properties": {"code": "HB_NORTH"}},
        {
            "label": "Instrument",
            "key": "ERCOT.DASPP.HB_NORTH",
            "properties": {"instrument_id": "ERCOT.DASPP.HB_NORTH"},
        },
    ]
    driver = FakeDriver(results={"RETURN i.instrument_id": exists, "DISTINCT": related})
    out = graph.related_instruments(driver, "ERCOT.SPP.HB_NORTH", depth=2)
    assert out["instrument_id"] == "ERCOT.SPP.HB_NORTH"
    assert {r["key"] for r in out["related"]} == {"HB_NORTH", "ERCOT.DASPP.HB_NORTH"}
