"""build_entity_graph: pure derivation of the entity catalog from vocabularies."""

from energex.core import graph


def _plan(observed=None):
    return graph.build_entity_graph(observed or graph.ObservedEntities())


def _node(plan, label, key):
    return next((n for n in plan.nodes if n.label == label and n.key == key), None)


def _edges(plan, rel_type):
    return [(e.src, e.dst) for e in plan.edges if e.rel_type == rel_type]


def test_static_catalog_nodes_exist_without_observations():
    plan = _plan()
    assert _node(plan, "Library", "power.lmp").properties["revision_mode"] == "bitemporal_merge"
    assert _node(plan, "Source", "fred") is not None
    assert _node(plan, "Market", "ERCOT") is not None
    assert _node(plan, "SettlementPoint", "HB_NORTH").properties["kind"] == "hub"
    assert _node(plan, "SettlementPoint", "LZ_HOUSTON").properties["kind"] == "load_zone"
    assert _node(plan, "Region", "TEXAS").properties["nclimdiv_code"] == "041"
    assert _node(plan, "Commodity", "NATGAS") is not None
    # ERCO is seeded statically: it is the EIA-930 <-> ERCOT join point
    assert _node(plan, "BalancingAuthority", "ERCO") is not None


def test_static_instruments_routed_via_symbology():
    plan = _plan()
    wti = _node(plan, "Instrument", "FRED.WTI.SPOT")
    assert wti.properties["symbol"] == "wti_spot"
    assert (("Instrument", "FRED.WTI.SPOT"), ("Library", "prices.spot")) in _edges(
        plan, "IN_LIBRARY"
    )
    assert (("Instrument", "FRED.WTI.SPOT"), ("Source", "fred")) in _edges(plan, "FROM_SOURCE")
    assert (("Instrument", "FRED.WTI.SPOT"), ("Commodity", "WTI")) in _edges(plan, "MEASURES")


def test_ercot_static_instruments_and_market_aggregate():
    plan = _plan()
    assert (("Instrument", "ERCOT.SPP.HB_NORTH"), ("SettlementPoint", "HB_NORTH")) in _edges(
        plan, "MEASURES"
    )
    assert _node(plan, "Instrument", "ERCOT.DASPP.LZ_WEST") is not None
    # ERCOT.LOAD.ERCOT measures the MARKET aggregate, not a settlement point
    assert (("Instrument", "ERCOT.LOAD.ERCOT"), ("Market", "ERCOT")) in _edges(plan, "MEASURES")
    assert (("SettlementPoint", "HB_NORTH"), ("Market", "ERCOT")) in _edges(plan, "IN_MARKET")


def test_observed_bas_produce_all_five_eia930_families():
    plan = _plan(graph.ObservedEntities(balancing_authorities=("MISO",)))
    for prefix, kind in [
        ("EIA930.D", "demand"),
        ("EIA930.DF", "demand_forecast"),
        ("EIA930.NG", "net_generation"),
        ("EIA930.TI", "interchange"),
        ("EIA930.GEN_FUEL", "generation_by_fuel"),
    ]:
        node = _node(plan, "Instrument", f"{prefix}.MISO")
        assert node is not None and node.properties["kind"] == kind
    assert (("Instrument", "EIA930.D.MISO"), ("BalancingAuthority", "MISO")) in _edges(
        plan, "MEASURES"
    )
    assert (
        ("Instrument", "EIA930.GEN_FUEL.MISO"),
        ("Library", "power.generation_by_fuel"),
    ) in _edges(plan, "IN_LIBRARY")


def test_fuel_types_and_generates_edges():
    plan = _plan(
        graph.ObservedEntities(
            balancing_authorities=("ERCO",), fuel_types_by_ba={"ERCO": ("NG", "WND")}
        )
    )
    assert _node(plan, "FuelType", "WND") is not None
    assert (("BalancingAuthority", "ERCO"), ("FuelType", "NG")) in _edges(plan, "GENERATES")
    # curated cross-domain edge appears only when fuel NG is observed
    assert (("Commodity", "NATGAS"), ("FuelType", "NG")) in _edges(plan, "FUELS")
    assert not _edges(_plan(), "FUELS")


def test_curated_cross_domain_edges():
    plan = _plan()
    assert (("BalancingAuthority", "ERCO"), ("Market", "ERCOT")) in _edges(plan, "OPERATES")
    assert (("Region", "TEXAS"), ("Market", "ERCOT")) in _edges(plan, "WEATHER_PROXY_FOR")


def test_plan_is_deduplicated_and_all_edge_endpoints_exist():
    plan = _plan(graph.ObservedEntities(balancing_authorities=("ERCO", "MISO")))
    keys = [(n.label, n.key) for n in plan.nodes]
    assert len(keys) == len(set(keys))
    node_set = set(keys)
    for e in plan.edges:
        assert e.src in node_set and e.dst in node_set
