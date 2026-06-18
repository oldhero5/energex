"""Service layer: the S2 read-only FastAPI seam (``readapi``) over ``energex.core.storage``.

The importable core (``energex.core.*``) has no web dependencies; this subpackage is the
deployable serving glue and imports the core, never the other way around. (The legacy
DuckDB+APScheduler serving app and CLI were removed once Dagster ingestion + the readapi
serving seam superseded them.)
"""
