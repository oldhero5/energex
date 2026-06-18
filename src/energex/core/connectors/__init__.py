"""Source connectors: vendor APIs -> FetchResult (pandas at the boundary).

These live in energex.core and stay framework-agnostic (no dagster/fastapi/langgraph,
enforced by tests/test_core_has_no_framework_imports.py). They also MUST NOT import
arcticdb — the connector layer never touches storage, so importing a connector can
never trip the phase-0 AWS-SDK load-order hazard.
"""

from energex.core.connectors.base import Connector, FetchResult

__all__ = ["Connector", "FetchResult"]
