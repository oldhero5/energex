"""Top-level Dagster Definitions. Phase 1 wires everything empty but loadable."""

import dagster as dg

from energex.orchestration.assets import ASSETS
from energex.orchestration.checks import CHECKS
from energex.orchestration.reconcile import RECONCILE_ASSETS
from energex.orchestration.resources import RESOURCES
from energex.orchestration.schedules import SCHEDULES
from energex.orchestration.sensors import SENSORS

defs = dg.Definitions(
    assets=[*ASSETS, *RECONCILE_ASSETS],
    asset_checks=CHECKS,
    schedules=SCHEDULES,
    sensors=SENSORS,
    resources=RESOURCES,
)
