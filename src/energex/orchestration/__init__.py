"""energex.orchestration — the ONLY package that imports dagster (S1 write-side).

Populated phase-by-phase (spec §5.6/§5.10). Phase 1 ships an empty, loadable
Definitions so `uv run dagster dev` boots with no errors.
"""
