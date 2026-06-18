"""energex.core — framework-agnostic business contracts.

CI-enforced invariant: this package must NEVER import dagster, fastapi, or
langgraph (see tests/test_core_has_no_framework_imports.py).
"""
