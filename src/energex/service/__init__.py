"""Service layer: FastAPI app + in-process scheduler that wraps the energex core.

The importable core (``energex.data_fetcher``, ``energex.database``, ``energex.analysis``,
...) has no web/scheduler dependencies; this subpackage is the deployable glue and
imports the core, never the other way around.
"""
