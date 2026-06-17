"""The empty orchestration.Definitions must build and validate (spec §9 gate)."""

import subprocess

import dagster as dg


def test_definitions_builds():
    from energex.orchestration.definitions import defs

    assert isinstance(defs, dg.Definitions)
    # Empty in phase 1 — nothing to resolve, but the object must be well-formed.
    # (dagster 1.13.9 has no get_all_asset_specs; resolve the repository instead.)
    assert list(defs.assets) == []
    repo = defs.get_repository_def()
    assert list(repo.assets_defs_by_key) == []


def test_dagster_definitions_validate_cli():
    result = subprocess.run(
        ["uv", "run", "dagster", "definitions", "validate",
         "-m", "energex.orchestration.definitions"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Validation successful" in (result.stdout + result.stderr)
