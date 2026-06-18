"""Schedules for the always-on ingestion stack (spec §5.6).

Each schedule targets a partitioned asset job and, on every tick, materializes the most
recent partition (resolved against the tick's scheduled execution time). Crons always set
``execution_timezone`` (the backend runs TZ=UTC; wall-clock release times are expressed
only here, so the cadence is DST-correct). ``intraday_futures_bars`` is intentionally NOT
scheduled — Yahoo/yfinance is blocked, so a tick would only fire failing runs; it stays
manual.
"""

from typing import Any

import dagster as dg

from energex.orchestration.assets import (
    eia_gas_storage,
    eia_petroleum_status,
    fred_spot_prices,
    noaa_degree_days,
)
from energex.orchestration.partitions import (
    EIA_GAS_WEEKLY,
    EIA_PETROLEUM_WEEKLY,
    FRED_DAILY,
    NOAA_MONTHLY,
)

# One job per scheduled asset. Selecting the asset also pulls in its asset_check.
_eia_gas_job = dg.define_asset_job(
    "eia_gas_storage_job", selection=dg.AssetSelection.assets(eia_gas_storage)
)
_eia_petroleum_job = dg.define_asset_job(
    "eia_petroleum_status_job", selection=dg.AssetSelection.assets(eia_petroleum_status)
)
_noaa_job = dg.define_asset_job(
    "noaa_degree_days_job", selection=dg.AssetSelection.assets(noaa_degree_days)
)
_fred_job = dg.define_asset_job(
    "fred_spot_prices_job", selection=dg.AssetSelection.assets(fred_spot_prices)
)


def _latest_partition_request(
    context: dg.ScheduleEvaluationContext, partitions_def: dg.TimeWindowPartitionsDefinition
) -> dg.RunRequest | dg.SkipReason:
    """Materialize the most recent partition as of the tick's scheduled execution time."""
    keys = partitions_def.get_partition_keys(current_time=context.scheduled_execution_time)
    if not keys:
        return dg.SkipReason("no partition available yet")
    return dg.RunRequest(partition_key=keys[-1])


# EIA natural-gas weekly storage releases Thursday 10:30 ET; fire just after.
@dg.schedule(
    job=_eia_gas_job,
    cron_schedule="35 10 * * 4",
    execution_timezone="America/New_York",
    name="eia_gas_storage_schedule",
)
def eia_gas_storage_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _latest_partition_request(context, EIA_GAS_WEEKLY)


# EIA weekly petroleum status (crude stocks) releases Wednesday 10:30 ET; fire just after.
@dg.schedule(
    job=_eia_petroleum_job,
    cron_schedule="35 10 * * 3",
    execution_timezone="America/New_York",
    name="eia_petroleum_status_schedule",
)
def eia_petroleum_status_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _latest_partition_request(context, EIA_PETROLEUM_WEEKLY)


# NOAA nClimDiv monthly file lands a few days into the following month; pull on the 6th.
@dg.schedule(
    job=_noaa_job,
    cron_schedule="0 12 6 * *",
    execution_timezone="America/New_York",
    name="noaa_degree_days_schedule",
)
def noaa_degree_days_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _latest_partition_request(context, NOAA_MONTHLY)


# FRED daily benchmark spot prices publish with a few-business-day lag; pull weekday mornings.
@dg.schedule(
    job=_fred_job,
    cron_schedule="30 9 * * 1-5",
    execution_timezone="America/New_York",
    name="fred_spot_prices_schedule",
)
def fred_spot_prices_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _latest_partition_request(context, FRED_DAILY)


SCHEDULES: list[Any] = [
    eia_gas_storage_schedule,
    eia_petroleum_status_schedule,
    noaa_degree_days_schedule,
    fred_spot_prices_schedule,
]
