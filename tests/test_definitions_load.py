"""The orchestration.Definitions must build, wire the intraday slice, and validate."""

import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg


def test_definitions_builds_with_intraday_slice():
    from energex.orchestration.definitions import defs

    assert isinstance(defs, dg.Definitions)

    repo = defs.get_repository_def()
    asset_keys = {key.to_user_string() for key in repo.assets_defs_by_key}
    assert "intraday_futures_bars" in asset_keys
    assert "fred_spot_prices" in asset_keys
    assert "noaa_degree_days" in asset_keys
    assert "eia_gas_storage" in asset_keys
    assert "eia_petroleum_status" in asset_keys
    assert "eia930_region" in asset_keys
    assert "eia930_generation_by_fuel" in asset_keys
    assert "ercot_rt_spp" in asset_keys
    assert "ercot_dam_spp" in asset_keys
    assert "ercot_load" in asset_keys

    # asset_checks MUST be wired explicitly (spec §5.6); key by check name.
    check_keys = {key.name for key in repo.asset_checks_defs_by_key}
    assert "intraday_bars_pass_quality_gate" in check_keys
    assert "fred_spot_prices_pass_quality_gate" in check_keys
    assert "noaa_degree_days_pass_quality_gate" in check_keys
    assert "eia_gas_storage_pass_quality_gate" in check_keys
    assert "eia_petroleum_status_pass_quality_gate" in check_keys
    assert "eia930_region_pass_quality_gate" in check_keys
    assert "eia930_generation_by_fuel_pass_quality_gate" in check_keys
    assert "ercot_rt_spp_pass_quality_gate" in check_keys
    assert "ercot_dam_spp_pass_quality_gate" in check_keys
    assert "ercot_load_pass_quality_gate" in check_keys


def test_dagster_definitions_validate_cli():
    # Invoke dagster via the current interpreter so it uses THIS test environment
    # (with the orchestration extra) rather than re-resolving a fresh default env.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dagster",
            "definitions",
            "validate",
            "-m",
            "energex.orchestration.definitions",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Validation successful" in (result.stdout + result.stderr)


def test_ercot_schedules_target_correct_operating_day():
    import dagster as dg

    from energex.orchestration.schedules import (
        ercot_dam_spp_schedule,
        ercot_load_schedule,
        ercot_rt_spp_schedule,
    )

    # 14:00 CPT on operating day D: RT/load capture D (today, intraday); DAM captures D+1
    # (the next-day curve that cleared midday). A "latest-ended partition" heuristic would
    # wrongly select D-1 for all three.
    tick = datetime(2026, 6, 15, 14, 0, tzinfo=ZoneInfo("America/Chicago"))
    ctx = dg.build_schedule_context(scheduled_execution_time=tick)
    assert ercot_rt_spp_schedule(ctx).partition_key == "2026-06-15"
    assert ercot_load_schedule(ctx).partition_key == "2026-06-15"
    assert ercot_dam_spp_schedule(ctx).partition_key == "2026-06-16"
