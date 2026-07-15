"""entity_graph asset: store-driven discovery -> pure plan -> idempotent sync."""

from types import SimpleNamespace

import dagster as dg
import pandas as pd


class FakeDriver:
    def __init__(self, results=None):
        self.calls = []
        self._results = results or {}

    def execute_query(self, query_, parameters_=None, database_=None, **_kw):
        self.calls.append((query_, dict(parameters_ or {}), database_))
        for needle, records in self._results.items():
            if needle in query_:
                return SimpleNamespace(records=records, summary=None, keys=[])
        return SimpleNamespace(records=[], summary=None, keys=[])

    def close(self):
        pass


class FakeLib:
    def __init__(self, symbols=(), frames=None):
        self._symbols = list(symbols)
        self._frames = frames or {}

    def list_symbols(self):
        return list(self._symbols)

    def tail(self, symbol, n):
        return SimpleNamespace(data=self._frames[symbol].tail(n))


class FakeArctic:
    """Stands in for ArcticDBResource: get_library(name) only."""

    def __init__(self, libs):
        self._libs = libs

    def get_library(self, name):
        return self._libs[name]


class FakeNeo4j:
    def __init__(self, driver):
        self.driver = driver


def _gen_fuel_frame(fuels):
    now = pd.Timestamp("2026-07-14", tz="UTC")
    return pd.DataFrame(
        {
            "instrument_id": ["EIA930.GEN_FUEL.ERCO"] * len(fuels),
            "valid_time": [now] * len(fuels),
            "fuel_type": list(fuels),
            "value": [1.0] * len(fuels),
        }
    )


def test_entity_graph_syncs_discovered_universe():
    from energex.orchestration.graph import entity_graph

    arctic = FakeArctic(
        {
            "power.demand": FakeLib(symbols=["erco", "miso"]),
            "power.generation_by_fuel": FakeLib(
                symbols=["erco"], frames={"erco": _gen_fuel_frame(["NG", "WND"])}
            ),
        }
    )
    driver = FakeDriver()
    result = entity_graph(dg.build_asset_context(), arctic=arctic, neo4j=FakeNeo4j(driver))
    assert isinstance(result, dg.MaterializeResult)
    assert result.metadata["balancing_authorities"] == 2
    assert result.metadata["fuel_types"] == 2
    assert any("UNWIND" in q for q, _, _ in driver.calls)


def test_entity_graph_degrades_to_static_catalog_when_store_empty():
    from energex.orchestration.graph import entity_graph

    class EmptyArctic:
        def get_library(self, name):
            raise RuntimeError("no such library")

    driver = FakeDriver()
    result = entity_graph(dg.build_asset_context(), arctic=EmptyArctic(), neo4j=FakeNeo4j(driver))
    # static catalog still syncs: 13 settlement points among the node batches
    assert result.metadata["nodes_total"] > 40
    assert result.metadata["balancing_authorities"] == 0


def test_integrity_check_flags_unresolvable_instruments():
    from energex.orchestration.graph import entity_graph_instruments_resolve

    good = {"label": "Instrument", "key": "FRED.WTI.SPOT", "properties": {}}
    bad = {"label": "Instrument", "key": "BOGUS.NOPE", "properties": {}}
    result = entity_graph_instruments_resolve(
        dg.build_asset_context(), neo4j=FakeNeo4j(FakeDriver(results={"MATCH": [good, bad]}))
    )
    assert isinstance(result, dg.AssetCheckResult)
    assert result.passed is False

    ok = entity_graph_instruments_resolve(
        dg.build_asset_context(), neo4j=FakeNeo4j(FakeDriver(results={"MATCH": [good]}))
    )
    assert ok.passed is True


def test_integrity_check_fails_on_empty_graph():
    from energex.orchestration.graph import entity_graph_instruments_resolve

    result = entity_graph_instruments_resolve(
        dg.build_asset_context(), neo4j=FakeNeo4j(FakeDriver())
    )
    assert result.passed is False
