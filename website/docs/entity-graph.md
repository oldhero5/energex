---
id: entity-graph
title: Entity Graph (Neo4j)
sidebar_label: Entity Graph
---

# Entity Graph

Every number in Energex lives in ArcticDB, keyed by `instrument_id`. The **entity
graph** is the *what/who/connected* layer around those ids: a small Neo4j catalog of
the entities the instrument namespace implies — balancing authorities, ERCOT
settlement points, NOAA climate regions, commodities, fuel types — plus a curated set
of cross-domain edges. It answers questions the time-series store cannot:

- *What instruments exist for ERCOT, and how do they relate?* (discovery for the
  frontend cockpit and watchlists)
- *"Houston power prices"* → `ERCOT.SPP.HB_HOUSTON`, `ERCOT.SPP.LZ_HOUSTON`,
  `ERCOT.DASPP.…` (entity grounding for the S3 agent)
- *Which balancing authorities generate wind? What weather series proxies the ERCOT
  footprint?* (cross-domain navigation)

The invariant, stated in `core/symbology.py` since phase 1: **the graph references
instrument_ids and never owns a number.** Nodes and edges carry identity plus
`first_seen`/`last_seen` knowledge stamps — no values, no ArcticDB version integers —
so the graph [restores independently](./operations.md) of the store of record.

## Data model

| Label | Key | Notable properties |
| --- | --- | --- |
| `Instrument` | `instrument_id` | `symbol`, `kind` (demand, lmp, spot, …) |
| `Library` | `name` | `revision_mode` |
| `Source` | `name` (eia, eia930, ercot, fred, noaa, yfinance) | — |
| `Market` | `code` (`ERCOT`) | `name` |
| `BalancingAuthority` | `code` (EIA-930 respondent, e.g. `ERCO`) | — |
| `SettlementPoint` | `code` (e.g. `HB_NORTH`) | `kind`: `hub` \| `load_zone` |
| `Region` | `code` (NOAA nClimDiv token, e.g. `TEXAS`) | `nclimdiv_code` |
| `Commodity` | `code` (`WTI`, `BRENT`, `NATGAS`) | `name` |
| `FuelType` | `code` (observed EIA-930 fueltype, e.g. `NG`, `WND`) | — |

Relationships:

- `(Instrument)-[:IN_LIBRARY]->(Library)` and `(Instrument)-[:FROM_SOURCE]->(Source)`
  — catalog plumbing, routed through `symbology.resolve`.
- `(Instrument)-[:MEASURES]->(BalancingAuthority | SettlementPoint | Region | Commodity | Market)`
  — the entity a series is *about*. `ERCOT.LOAD.ERCOT` measures the **market
  aggregate**, not a settlement point.
- `(SettlementPoint)-[:IN_MARKET]->(Market)` — the 13 canonical tradeable points.
- `(BalancingAuthority)-[:GENERATES]->(FuelType)` — observed generation-by-fuel mix.
  :::caution
  Currently **under-reported**: the degenerate write path deduplicates
  generation-by-fuel rows on timestamp alone, so only one fuel per (BA, hour)
  survives in storage today. The discovery reads whatever the store has and heals
  automatically once that storage fix lands; until then expect one or two fuels per
  BA, not the full mix.
  :::
- Curated cross-domain edges: `(ERCO)-[:OPERATES]->(ERCOT)` (the EIA-930 ↔ ERCOT
  nodal join point), `(TEXAS)-[:WEATHER_PROXY_FOR]->(ERCOT)` (nClimDiv Texas is the
  documented ERCOT footprint), and `(NATGAS)-[:FUELS]->(NG)` when gas-fired
  generation is observed.

Deliberately **not** modeled: BA↔BA interchange pairs (only *total* interchange is
ingested), per-vintage lineage (that is the ArcticDB vintage index's job), and the
~17k non-tradeable ERCOT nodes (no data behind them).

## How it syncs

`energex.core.graph` is a pure module: `build_entity_graph(observed)` derives a
`GraphPlan` from the symbology tables, the ERCOT settlement-point set, and the NOAA
region map, plus **store-observed** vocabulary — balancing authorities from
`power.demand` symbols and fuel types from a bounded tail read of
`power.generation_by_fuel`. The repo hardcodes no BA or fuel list anywhere; the graph
discovers them. The plan compiles to batched `UNWIND … MERGE` Cypher (one statement
per label / relationship shape), stamped `first_seen` on create and `last_seen` on
every sync — running it twice is a no-op apart from `last_seen`.

The Dagster side (`energex.orchestration.graph`) wires that into an `entity_graph`
asset (group `graph`) with a `Neo4jResource`, an `entity_graph_instruments_resolve`
asset check (every `Instrument` node read back must resolve through
`core.symbology` — catches drift), and a daily `entity_graph_schedule` at 06:10 ET.

The neo4j driver itself is imported lazily in exactly one function
(`core.graph.create_driver`), so installs without the `graph` extra — and every test
environment — never import it. Tests run against a duck-typed fake driver; no Neo4j
service exists in CI.

## Querying it

Through the S2 read API (the only surface the frontend consumes):

| Method & path | Query params | Returns |
|---|---|---|
| `GET /graph/entities` | `label?` | catalog nodes `[{label, key, properties}, …]` |
| `GET /graph/related` | `instrument_id`, `depth?` (1–3, default 2) | connected entities + sibling instruments |

`/graph/related` traverses **semantic** relationships only (`MEASURES`, `IN_MARKET`,
`OPERATES`, `WEATHER_PROXY_FOR`, `GENERATES`, `FUELS`) — never through the
`Library`/`Source` hub nodes, which would relate everything to everything. Depth 1
returns the entities an instrument measures; depth 2 adds sibling instruments and
adjacent entities.

The graph is **optional**: the api starts and serves all series endpoints with no
Neo4j running (`dev`/`api` compose profiles have none), `/graph/*` returns **503**
until the `full` profile's neo4j is reachable, and the driver connects lazily on the
first graph request — no api restart needed after neo4j comes up. `/healthz` carries
a `graph: bool` reflecting the cached connection state.

Or directly in the Neo4j browser (http://localhost:7474):

```cypher
// what relates to the ERCOT North Hub?
MATCH (i:Instrument {instrument_id: "ERCOT.SPP.HB_NORTH"})-[r]-(n)
RETURN i, r, n;

// which balancing authorities generate wind?
MATCH (ba:BalancingAuthority)-[:GENERATES]->(:FuelType {code: "WND"})
RETURN ba.code ORDER BY ba.code;
```

## Knowledge-time honesty

The graph is a **current-state catalog**, not a bitemporal store — it has no `as_of`
parameter by design. What it does carry is provenance: every node and relationship
records `first_seen` (when the entity entered the catalog) and `last_seen` (the most
recent sync that still observed it), so consumers can always tell how fresh a catalog
fact is. Anything time-series-shaped stays in ArcticDB behind `read_as_of`.

## Operations

- Runs under the `full` compose profile only (`neo4j:5.26.0-community`, bolt 7687,
  browser 7474, 512m heap + 512m pagecache).
- Keep `NEO4J_AUTH` (server, compose-only) and `NEO4J_PASSWORD` (clients) in sync —
  rotating one without the other fails auth at graph-run time.
- Back up via `neo4j-admin database dump` of the `neo4j-data` volume (see
  [Operations](./operations.md)); the graph restores independently of ArcticDB, and a
  lost graph is fully rebuilt by one `entity_graph` materialization.
