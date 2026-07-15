"""Neo4j entity graph (phase 9): the what/who/connected layer over the catalog.

Numbers live in ArcticDB; this module mirrors IDENTITY only — instrument_ids
(symbology), the entities those ids imply (balancing authorities, ERCOT
settlement points, NOAA regions, commodities, fuel types) and a small curated
set of cross-domain edges. Writes are idempotent MERGE upserts stamped with
first_seen/last_seen knowledge times, so the graph restores independently of
the store of record (operations doc) and never misrepresents when an entity
entered the catalog.

Pure by construction: the neo4j driver is imported lazily inside
create_driver() only; plan building and Cypher generation are side-effect-free,
and sync/query helpers accept any object exposing execute_query() (duck-typed)
so tests inject fakes and installs without the `graph` extra never break.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from energex.core import symbology
from energex.core.config import Neo4jConfig
from energex.core.connectors import ercot
from energex.core.connectors.weather import REGIONS
from energex.core.exceptions import GraphError

# Label -> unique key property. The only labels sync will ever create; Cypher
# labels cannot be parameterized, so they are always drawn from this dict.
KEY_PROPERTY: dict[str, str] = {
    "Source": "name",
    "Library": "name",
    "Instrument": "instrument_id",
    "Market": "code",
    "BalancingAuthority": "code",
    "SettlementPoint": "code",
    "Region": "code",
    "Commodity": "code",
    "FuelType": "code",
}

# Relationship types traversed by /graph/related. IN_LIBRARY and FROM_SOURCE are
# deliberately excluded: they are catalog plumbing, and traversing through those
# hub nodes would relate every instrument to every other one.
SEMANTIC_RELS: tuple[str, ...] = (
    "MEASURES",
    "IN_MARKET",
    "OPERATES",
    "WEATHER_PROXY_FOR",
    "GENERATES",
    "FUELS",
)

# instrument_id prefix -> connector source string (each connector's _SOURCE).
_PREFIX_SOURCE: dict[str, str] = {
    "EIA930": "eia930",
    "ERCOT": "ercot",
    "EIA": "eia",
    "FRED": "fred",
    "NOAA": "noaa",
    "CME": "yfinance",
}

# library -> instrument kind (measurement family). Keys mirror symbology.LIBRARY_MODE.
_LIBRARY_KIND: dict[str, str] = {
    "fundamentals.eia": "fundamentals",
    "weather": "degree_days",
    "prices.spot": "spot",
    "prices.intraday": "intraday",
    "prices.futures": "futures",
    "power.demand": "demand",
    "power.demand_forecast": "demand_forecast",
    "power.generation": "net_generation",
    "power.interchange": "interchange",
    "power.generation_by_fuel": "generation_by_fuel",
    "power.lmp": "lmp",
    "power.load": "load",
    "power.dalmp": "dalmp",
}

_COMMODITIES: dict[str, str] = {
    "WTI": "WTI crude oil",
    "BRENT": "Brent crude oil",
    "NATGAS": "Natural gas",
}

# Static instrument -> the commodity it measures. EIA.PET.CRUDE.STOCKS maps to
# WTI as the US crude benchmark its stocks move.
_STATIC_COMMODITY: dict[str, str] = {
    "FRED.WTI.SPOT": "WTI",
    "FRED.BRENT.SPOT": "BRENT",
    "FRED.HENRYHUB.SPOT": "NATGAS",
    "CME.CL.FRONT": "WTI",
    "CME.BZ.FRONT": "BRENT",
    "CME.NG.FRONT": "NATGAS",
    "CME.CL.CLF26": "WTI",
    "CME.CL.CLG26": "WTI",
    "EIA.NG.STORAGE.LOWER48": "NATGAS",
    "EIA.PET.CRUDE.STOCKS": "WTI",
}

# EIA930 instrument prefixes per BA (all five families exist for every BA).
_EIA930_PREFIXES: tuple[str, ...] = (
    "EIA930.D",
    "EIA930.DF",
    "EIA930.NG",
    "EIA930.TI",
    "EIA930.GEN_FUEL",
)


@dataclass(frozen=True)
class GraphNode:
    label: str
    key: str
    properties: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    rel_type: str
    src: tuple[str, str]  # (label, key)
    dst: tuple[str, str]


@dataclass(frozen=True)
class GraphPlan:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


@dataclass(frozen=True)
class ObservedEntities:
    """Store-discovered vocabulary (the repo deliberately hardcodes no BA/fuel
    lists): BA codes from power.demand symbols, fuel types per BA from
    power.generation_by_fuel frames. Uppercase codes."""

    balancing_authorities: tuple[str, ...] = ()
    fuel_types_by_ba: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphSyncResult:
    nodes_by_label: dict[str, int]
    edges_by_type: dict[str, int]


class _PlanBuilder:
    def __init__(self) -> None:
        self._nodes: dict[tuple[str, str], dict[str, str]] = {}
        self._edges: dict[tuple[str, tuple[str, str], tuple[str, str]], None] = {}

    def node(self, label: str, key: str, **props: str) -> tuple[str, str]:
        merged = self._nodes.setdefault((label, key), {})
        merged.update(props)
        return (label, key)

    def edge(self, rel_type: str, src: tuple[str, str], dst: tuple[str, str]) -> None:
        self._edges[(rel_type, src, dst)] = None

    def build(self) -> GraphPlan:
        nodes = tuple(
            GraphNode(label=label, key=key, properties=dict(props))
            for (label, key), props in sorted(self._nodes.items())
        )
        edges = tuple(
            GraphEdge(rel_type=rel, src=src, dst=dst) for (rel, src, dst) in sorted(self._edges)
        )
        return GraphPlan(nodes=nodes, edges=edges)


def _source_for(instrument_id: str) -> str:
    head = instrument_id.split(".", 1)[0]
    # EIA930 shares the EIA head only lexically; exact head match keeps them apart.
    return _PREFIX_SOURCE[head]


def _instrument(builder: _PlanBuilder, instrument_id: str) -> tuple[str, str]:
    library, symbol = symbology.resolve(instrument_id)
    node = builder.node("Instrument", instrument_id, symbol=symbol, kind=_LIBRARY_KIND[library])
    builder.edge("IN_LIBRARY", node, builder.node("Library", library))
    builder.edge("FROM_SOURCE", node, builder.node("Source", _source_for(instrument_id)))
    return node


def build_entity_graph(observed: ObservedEntities | None = None) -> GraphPlan:
    """Derive the full entity catalog. Pure: no I/O, no driver."""
    observed = observed or ObservedEntities()
    b = _PlanBuilder()

    for library, mode in symbology.LIBRARY_MODE.items():
        b.node("Library", library, revision_mode=mode)
    for source in sorted(set(_PREFIX_SOURCE.values())):
        b.node("Source", source)
    for code, name in _COMMODITIES.items():
        b.node("Commodity", code, name=name)

    market = b.node("Market", "ERCOT", name="Electric Reliability Council of Texas")
    for point in sorted(ercot.settlement_points()):
        kind = "hub" if point.startswith("HB_") else "load_zone"
        b.edge("IN_MARKET", b.node("SettlementPoint", point, kind=kind), market)
        b.edge("MEASURES", _instrument(b, f"ERCOT.SPP.{point}"), ("SettlementPoint", point))
        b.edge("MEASURES", _instrument(b, f"ERCOT.DASPP.{point}"), ("SettlementPoint", point))
    # ERCOT.LOAD.ERCOT's tail is the market-wide aggregate, not a settlement point.
    b.edge("MEASURES", _instrument(b, "ERCOT.LOAD.ERCOT"), market)

    for nclimdiv_code, token in REGIONS.items():
        b.node("Region", token, nclimdiv_code=nclimdiv_code)

    for instrument_id in symbology.instruments():
        node = _instrument(b, instrument_id)
        if instrument_id.startswith("NOAA.HDD."):
            token = instrument_id.rpartition(".")[2]
            b.edge("MEASURES", node, ("Region", token))
        commodity = _STATIC_COMMODITY.get(instrument_id)
        if commodity is not None:
            b.edge("MEASURES", node, ("Commodity", commodity))

    # ERCO is seeded statically: it is the join point between the EIA-930 BA
    # universe and the ERCOT nodal universe, whether or not it was observed yet.
    bas = sorted(set(observed.balancing_authorities) | {"ERCO"})
    for ba in bas:
        ba_node = b.node("BalancingAuthority", ba)
        for prefix in _EIA930_PREFIXES:
            b.edge("MEASURES", _instrument(b, f"{prefix}.{ba}"), ba_node)

    fuel_types: set[str] = set()
    for ba, fuels in sorted(observed.fuel_types_by_ba.items()):
        for fuel in sorted(set(fuels)):
            fuel_types.add(fuel)
            b.edge("GENERATES", ("BalancingAuthority", ba), b.node("FuelType", fuel))

    # Curated cross-domain edges.
    b.edge("OPERATES", ("BalancingAuthority", "ERCO"), market)
    b.edge("WEATHER_PROXY_FOR", ("Region", "TEXAS"), market)
    if "NG" in fuel_types:  # gas-fired generation links power to the gas complex
        b.edge("FUELS", ("Commodity", "NATGAS"), ("FuelType", "NG"))

    return b.build()


def constraint_statements() -> list[str]:
    """One uniqueness constraint per label key; IF NOT EXISTS keeps it idempotent."""
    return [
        (
            f"CREATE CONSTRAINT {label.lower()}_{key}_unique IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
        )
        for label, key in KEY_PROPERTY.items()
    ]


def plan_to_cypher(plan: GraphPlan, *, synced_at: datetime) -> list[tuple[str, dict[str, Any]]]:
    """Batched idempotent upserts: one UNWIND+MERGE statement per node label and
    per (rel_type, src_label, dst_label). Labels/rel-types come only from our
    fixed vocabulary (Cypher cannot parameterize them); values are parameters."""
    statements: list[tuple[str, dict[str, Any]]] = []

    by_label: dict[str, list[GraphNode]] = {}
    for node in plan.nodes:
        if node.label not in KEY_PROPERTY:
            raise GraphError(f"unknown label {node.label!r}")
        by_label.setdefault(node.label, []).append(node)
    for label, nodes in by_label.items():
        key = KEY_PROPERTY[label]
        node_rows = [{"key": n.key, "props": dict(n.properties)} for n in nodes]
        statements.append(
            (
                f"UNWIND $rows AS row\n"
                f"MERGE (n:{label} {{{key}: row.key}})\n"
                f"ON CREATE SET n.first_seen = $synced_at\n"
                f"SET n += row.props, n.last_seen = $synced_at",
                {"rows": node_rows, "synced_at": synced_at},
            )
        )

    by_shape: dict[tuple[str, str, str], list[GraphEdge]] = {}
    for edge in plan.edges:
        by_shape.setdefault((edge.rel_type, edge.src[0], edge.dst[0]), []).append(edge)
    for (rel_type, src_label, dst_label), edges in by_shape.items():
        if src_label not in KEY_PROPERTY or dst_label not in KEY_PROPERTY:
            raise GraphError(f"unknown label in edge {rel_type!r}")
        src_key, dst_key = KEY_PROPERTY[src_label], KEY_PROPERTY[dst_label]
        edge_rows = [{"src": e.src[1], "dst": e.dst[1]} for e in edges]
        statements.append(
            (
                f"UNWIND $rows AS row\n"
                f"MERGE (a:{src_label} {{{src_key}: row.src}})\n"
                f"MERGE (b:{dst_label} {{{dst_key}: row.dst}})\n"
                f"MERGE (a)-[r:{rel_type}]->(b)\n"
                f"ON CREATE SET r.first_seen = $synced_at\n"
                f"SET r.last_seen = $synced_at",
                {"rows": edge_rows, "synced_at": synced_at},
            )
        )
    return statements


def sync_graph(
    driver: Any,
    plan: GraphPlan,
    *,
    synced_at: datetime | None = None,
    database: str | None = None,
) -> GraphSyncResult:
    """Idempotent MERGE upsert of the whole plan. ``driver`` is duck-typed
    (anything with execute_query). Errors are wrapped redacted — exception type
    only, never the message, which may embed a connection URI."""
    stamp = synced_at or datetime.now(timezone.utc)
    try:
        for statement in constraint_statements():
            driver.execute_query(statement, parameters_={}, database_=database)
        for query, params in plan_to_cypher(plan, synced_at=stamp):
            driver.execute_query(query, parameters_=params, database_=database)
    except GraphError:
        raise
    except Exception as exc:
        raise GraphError(f"entity-graph sync failed: {type(exc).__name__}") from None

    nodes_by_label: dict[str, int] = {}
    for node in plan.nodes:
        nodes_by_label[node.label] = nodes_by_label.get(node.label, 0) + 1
    edges_by_type: dict[str, int] = {}
    for edge in plan.edges:
        edges_by_type[edge.rel_type] = edges_by_type.get(edge.rel_type, 0) + 1
    return GraphSyncResult(nodes_by_label=nodes_by_label, edges_by_type=edges_by_type)


def _redact_uri(uri: str) -> str:
    """Strip any userinfo from a bolt/neo4j URI before it can reach a log line."""
    scheme, sep, rest = uri.partition("://")
    if sep and "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    return f"{scheme}{sep}{rest}"


def create_driver(cfg: Neo4jConfig) -> Any:
    """The ONLY place the neo4j driver is imported (lazily): installs without the
    `graph` extra can import this module freely and get a GraphError only when
    they actually try to connect."""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise GraphError("neo4j driver not installed — install the 'graph' extra") from exc
    password = cfg.password.get_secret_value() if cfg.password else ""
    try:
        # 5s connect cap keeps optional-graph startups snappy when no server runs.
        driver = GraphDatabase.driver(cfg.uri, auth=(cfg.user, password), connection_timeout=5.0)
        driver.verify_connectivity()
    except Exception as exc:
        raise GraphError(
            f"Neo4j connection failed (uri={_redact_uri(cfg.uri)}): {type(exc).__name__}"
        ) from None
    return driver


def _clean_value(value: Any) -> Any:
    if hasattr(value, "to_native"):  # neo4j.time.DateTime and friends
        value = value.to_native()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _clean_props(props: Mapping[str, Any]) -> dict[str, Any]:
    return {k: _clean_value(v) for k, v in props.items()}


def _keyed_case() -> str:
    """CASE arm extracting each label's key property (labels are code-fixed)."""
    return " ".join(f"WHEN '{label}' THEN n.{key}" for label, key in KEY_PROPERTY.items())


def list_entities(
    driver: Any, *, label: str | None = None, database: str | None = None
) -> list[dict[str, Any]]:
    """Catalog listing for the S2 seam: [{label, key, properties}, ...]."""
    if label is not None and label not in KEY_PROPERTY:
        raise GraphError(f"unknown label {label!r}")
    match = f"MATCH (n:{label})" if label else "MATCH (n)"
    query = (
        f"{match}\n"
        f"RETURN labels(n)[0] AS label,\n"
        f"       CASE labels(n)[0] {_keyed_case()} END AS key,\n"
        f"       properties(n) AS properties\n"
        f"ORDER BY label, key"
    )
    try:
        result = driver.execute_query(query, parameters_={}, database_=database)
    except Exception as exc:
        raise GraphError(f"entity-graph query failed: {type(exc).__name__}") from None
    return [
        {
            "label": rec["label"],
            "key": rec["key"],
            "properties": _clean_props(rec["properties"]),
        }
        for rec in result.records
    ]


def related_instruments(
    driver: Any,
    instrument_id: str,
    *,
    depth: int = 2,
    database: str | None = None,
) -> dict[str, Any] | None:
    """Neighbors of an instrument through SEMANTIC_RELS only (never through the
    Library/Source hubs). depth 1 = the entities it measures; 2 adds sibling
    instruments and adjacent entities. Returns None when the id is not in the
    graph."""
    if depth not in (1, 2, 3):
        raise GraphError(f"depth must be 1..3, got {depth!r}")
    try:
        exists = driver.execute_query(
            "MATCH (i:Instrument {instrument_id: $iid}) RETURN i.instrument_id",
            parameters_={"iid": instrument_id},
            database_=database,
        )
        if not exists.records:
            return None
        rels = "|".join(SEMANTIC_RELS)
        # depth is validated above; rel types and labels are code-fixed vocabulary.
        query = (
            f"MATCH (i:Instrument {{instrument_id: $iid}})\n"
            f"MATCH (i)-[:{rels}*1..{depth}]-(n)\n"
            f"WHERE n <> i\n"
            f"WITH DISTINCT n\n"
            f"RETURN labels(n)[0] AS label,\n"
            f"       CASE labels(n)[0] {_keyed_case()} END AS key,\n"
            f"       properties(n) AS properties\n"
            f"ORDER BY label, key"
        )
        result = driver.execute_query(query, parameters_={"iid": instrument_id}, database_=database)
    except Exception as exc:
        raise GraphError(f"entity-graph query failed: {type(exc).__name__}") from None
    return {
        "instrument_id": instrument_id,
        "depth": depth,
        "related": [
            {
                "label": rec["label"],
                "key": rec["key"],
                "properties": _clean_props(rec["properties"]),
            }
            for rec in result.records
        ],
    }
