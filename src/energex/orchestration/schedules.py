"""Schedules for the always-on ingestion stack (spec §5.6).

Each schedule targets a partitioned asset job and, on every tick, materializes the most
recent partition (resolved against the tick's scheduled execution time). Crons always set
``execution_timezone`` (the backend runs TZ=UTC; wall-clock release times are expressed
only here, so the cadence is DST-correct). ``intraday_futures_bars`` is intentionally NOT
scheduled — Yahoo/yfinance is blocked, so a tick would only fire failing runs; it stays
manual.
"""

from datetime import timedelta
from typing import Any

import dagster as dg

from energex.orchestration.assets import (
    eia930_generation_by_fuel,
    eia930_region,
    eia_gas_storage,
    eia_petroleum_status,
    ercot_dam_spp,
    ercot_load,
    ercot_rt_spp,
    fred_spot_prices,
    noaa_degree_days,
)
from energex.orchestration.partitions import (
    EIA930_DAILY,
    EIA_GAS_WEEKLY,
    EIA_PETROLEUM_WEEKLY,
    ERCOT_DAILY,
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
_eia930_job = dg.define_asset_job(
    "eia930_job",
    selection=dg.AssetSelection.assets(eia930_region, eia930_generation_by_fuel),
)


def _latest_partition_request(
    context: dg.ScheduleEvaluationContext, partitions_def: dg.TimeWindowPartitionsDefinition
) -> dg.RunRequest | dg.SkipReason:
    """Materialize the most recent partition as of the tick's scheduled execution time."""
    keys = partitions_def.get_partition_keys(current_time=context.scheduled_execution_time)
    if not keys:
        return dg.SkipReason("no partition available yet")
    return dg.RunRequest(partition_key=keys[-1])


def _ercot_day_request(
    context: dg.ScheduleEvaluationContext,
    partitions_def: dg.TimeWindowPartitionsDefinition,
    *,
    day_offset: int,
) -> dg.RunRequest | dg.SkipReason:
    """Target an ERCOT operating day relative to the tick (in Central time). RT/load capture the
    CURRENT day intraday (offset 0); DAM publishes the NEXT day's curve midday (offset +1). The
    latest-ended-partition heuristic is wrong for both — it lags a full operating day."""
    tick = context.scheduled_execution_time  # tz-aware in execution_timezone (America/Chicago)
    key = (tick.date() + timedelta(days=day_offset)).isoformat()
    if key not in set(partitions_def.get_partition_keys(current_time=tick)):
        return dg.SkipReason(f"partition {key} not in range yet")
    return dg.RunRequest(partition_key=key)


# EIA natural-gas weekly storage releases Thursday 10:30 ET; fire just after.
@dg.schedule(
    job=_eia_gas_job,
    cron_schedule="35 10 * * 4",
    execution_timezone="America/New_York",
    name="eia_gas_storage_schedule",
    default_status=dg.DefaultScheduleStatus.RUNNING,
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
    default_status=dg.DefaultScheduleStatus.RUNNING,
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
    default_status=dg.DefaultScheduleStatus.RUNNING,
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
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def fred_spot_prices_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _latest_partition_request(context, FRED_DAILY)


# EIA-930 lands hourly with a ~1-2h lag; re-materialize today's partition every hour.
@dg.schedule(
    job=_eia930_job,
    cron_schedule="20 * * * *",
    execution_timezone="America/New_York",
    name="eia930_schedule",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def eia930_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _latest_partition_request(context, EIA930_DAILY)


_ercot_rt_spp_job = dg.define_asset_job(
    "ercot_rt_spp_job", selection=dg.AssetSelection.assets(ercot_rt_spp)
)
_ercot_dam_spp_job = dg.define_asset_job(
    "ercot_dam_spp_job", selection=dg.AssetSelection.assets(ercot_dam_spp)
)
_ercot_load_job = dg.define_asset_job(
    "ercot_load_job", selection=dg.AssetSelection.assets(ercot_load)
)


# RT SPP lands every 15 min; re-materialize the CURRENT operating day hourly (intraday).
@dg.schedule(
    job=_ercot_rt_spp_job,
    cron_schedule="25 * * * *",
    execution_timezone="America/Chicago",
    name="ercot_rt_spp_schedule",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def ercot_rt_spp_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _ercot_day_request(context, ERCOT_DAILY, day_offset=0)


# Actual system load posts hourly for the current operating day.
@dg.schedule(
    job=_ercot_load_job,
    cron_schedule="35 * * * *",
    execution_timezone="America/Chicago",
    name="ercot_load_schedule",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def ercot_load_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _ercot_day_request(context, ERCOT_DAILY, day_offset=0)


# DAM clears ~12:30-13:30 CPT for the NEXT operating day; fetch tomorrow's curve each afternoon.
@dg.schedule(
    job=_ercot_dam_spp_job,
    cron_schedule="0 14 * * *",
    execution_timezone="America/Chicago",
    name="ercot_dam_spp_schedule",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def ercot_dam_spp_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest | dg.SkipReason:
    return _ercot_day_request(context, ERCOT_DAILY, day_offset=1)


SCHEDULES: list[Any] = [
    eia_gas_storage_schedule,
    eia_petroleum_status_schedule,
    noaa_degree_days_schedule,
    fred_spot_prices_schedule,
    eia930_schedule,
    ercot_rt_spp_schedule,
    ercot_load_schedule,
    ercot_dam_spp_schedule,
]
