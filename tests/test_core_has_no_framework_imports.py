"""CI-enforced hexagonal boundary: energex.core is framework-agnostic.

Walks every .py file under src/energex/core and asserts none import dagster,
fastapi, or langgraph. This is the load-bearing invariant from spec §4/§9."""

import re
from pathlib import Path

import energex.core as core

FORBIDDEN = re.compile(
    r"^\s*(?:import|from)\s+(dagster|fastapi|langgraph)\b",
    re.MULTILINE,
)


def test_core_has_no_framework_imports():
    core_dir = Path(core.__file__).parent
    offenders: list[str] = []
    for py in sorted(core_dir.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        if FORBIDDEN.search(text):
            offenders.append(str(py.relative_to(core_dir)))
    assert not offenders, f"framework imports found in energex.core: {offenders}"
