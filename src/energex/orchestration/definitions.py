"""Top-level Dagster Definitions. Phase 1 wires everything empty but loadable."""

import dagster as dg

from energex.orchestration.assets import ASSETS
from energex.orchestration.checks import CHECKS
from energex.orchestration.graph import GRAPH_ASSETS, GRAPH_CHECKS, GRAPH_SCHEDULES
from energex.orchestration.reconcile import RECONCILE_ASSETS
from energex.orchestration.resources import RESOURCES
from energex.orchestration.schedules import SCHEDULES
from energex.orchestration.sensors import SENSORS

defs = dg.Definitions(
    assets=[*ASSETS, *RECONCILE_ASSETS, *GRAPH_ASSETS],
    asset_checks=[*CHECKS, *GRAPH_CHECKS],
    schedules=[*SCHEDULES, *GRAPH_SCHEDULES],
    sensors=SENSORS,
    resources=RESOURCES,
)
