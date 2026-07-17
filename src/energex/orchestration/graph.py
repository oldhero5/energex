"""Entity-graph sync (phase 9): project the instrument catalog into Neo4j.

Discovery is store-driven (the repo deliberately hardcodes no BA/fuel lists):
balancing authorities come from ``power.demand`` symbols and fuel types from a
bounded tail read of ``power.generation_by_fuel``. The sync is an idempotent
MERGE upsert; ArcticDB remains the store of record and the graph never carries
a number. Missing power libraries degrade to the static catalog.
"""

from typing import Any

# arcticdb MUST load before pandas/pyarrow (phase-0 AWS-SDK load-order hazard).
import arcticdb  # noqa: F401
import dagster as dg

from energex.core import graph, symbology
from energex.core.config import Neo4jConfig
from energex.core.exceptions import GraphError, SymbologyError
from energex.orchestration.resources import ArcticDBResource, Neo4jResource

# Rows per generation_by_fuel tail read: ~hourly x ~10 fuels x 3 days, rounded up.
_FUEL_TAIL_ROWS = 1_000


def _observed_bas(arctic: ArcticDBResource) -> tuple[str, ...]:
    """BA codes = power.demand symbols (lowercased BA codes), uppercased back."""
    try:
        symbols = arctic.get_library("power.demand").list_symbols()
    except Exception:
        return ()
    return tuple(sorted(s.upper() for s in symbols))


def _observed_fuel_types(arctic: ArcticDBResource) -> dict[str, tuple[str, ...]]:
    """fuel_type values seen in the recent tail of each generation_by_fuel symbol."""
    try:
        lib = arctic.get_library("power.generation_by_fuel")
        symbols = lib.list_symbols()
    except Exception:
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for symbol in symbols:
        if symbol.endswith("__vintages"):
            continue
        try:
            frame = lib.tail(symbol, _FUEL_TAIL_ROWS).data
        except Exception:
            continue
        if "fuel_type" not in frame.columns or frame.empty:
            continue
        fuels = tuple(sorted(str(f) for f in frame["fuel_type"].dropna().unique()))
        if fuels:
            out[symbol.upper()] = fuels
    return out


@dg.asset(
    name="entity_graph",
    group_name="graph",
    compute_kind="neo4j",
    description=(
        "Idempotent MERGE sync of the entity catalog (instruments, balancing "
        "authorities, ERCOT settlement points, NOAA regions, commodities, fuel "
        "types) into Neo4j. References instrument_ids; never owns a number."
    ),
)
def entity_graph(
    context: dg.AssetExecutionContext, arctic: ArcticDBResource, neo4j: Neo4jResource
) -> dg.MaterializeResult:
    bas = _observed_bas(arctic)
    fuels = _observed_fuel_types(arctic)
    plan = graph.build_entity_graph(
        graph.ObservedEntities(balancing_authorities=bas, fuel_types_by_ba=fuels)
    )
    result = graph.sync_graph(neo4j.driver, plan)
    nodes_total = sum(result.nodes_by_label.values())
    edges_total = sum(result.edges_by_type.values())
    context.log.info(
        "entity graph synced: %d nodes, %d edges (%d BAs)", nodes_total, edges_total, len(bas)
    )
    fuel_universe: set[str] = set()
    for fuel_list in fuels.values():
        fuel_universe.update(fuel_list)
    return dg.MaterializeResult(
        metadata={
            "nodes_total": nodes_total,
            "edges_total": edges_total,
            "nodes_by_label": dg.MetadataValue.json(result.nodes_by_label),
            "edges_by_type": dg.MetadataValue.json(result.edges_by_type),
            "balancing_authorities": len(bas),
            "fuel_types": len(fuel_universe),
        }
    )


@dg.asset_check(
    asset="entity_graph",
    name="entity_graph_instruments_resolve",
    description=(
        "Every Instrument node read back from the graph must resolve through "
        "core.symbology — catches catalog drift between the graph and routing."
    ),
)
def entity_graph_instruments_resolve(
    context: dg.AssetCheckExecutionContext, neo4j: Neo4jResource
) -> dg.AssetCheckResult:
    rows = graph.list_entities(neo4j.driver, label="Instrument")
    if not rows:
        return dg.AssetCheckResult(
            passed=False, metadata={"reason": "no Instrument nodes in the graph"}
        )
    unresolvable: list[str] = []
    for row in rows:
        try:
            symbology.resolve(row["key"])
        except SymbologyError:
            unresolvable.append(row["key"])
    return dg.AssetCheckResult(
        passed=not unresolvable,
        metadata={
            "instruments": len(rows),
            "unresolvable": dg.MetadataValue.json(unresolvable[:20]),
        },
    )


_entity_graph_job = dg.define_asset_job(
    "entity_graph_job", selection=dg.AssetSelection.assets(entity_graph)
)


# Daily catalog refresh; 06:10 NY avoids the :20-:35 ingestion window. The graph
# is optional (neo4j runs only under the `full` compose profile), so the tick
# probes reachability and SKIPS instead of firing a guaranteed-failing run in
# profiles without a neo4j server.
@dg.schedule(
    job=_entity_graph_job,
    cron_schedule="10 6 * * *",
    execution_timezone="America/New_York",
    name="entity_graph_schedule",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def entity_graph_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    try:
        driver = graph.create_driver(Neo4jConfig())
    except GraphError:
        return dg.SkipReason("neo4j unreachable; entity-graph sync skipped (optional service)")
    driver.close()
    return dg.RunRequest()


GRAPH_ASSETS: list[Any] = [entity_graph]
GRAPH_CHECKS: list[Any] = [entity_graph_instruments_resolve]
GRAPH_SCHEDULES: list[Any] = [entity_graph_schedule]
