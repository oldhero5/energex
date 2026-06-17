"""The pre-write GATE (core.quality) and post-hoc AUDIT (analysis.quality)
are distinct modules with no name collision and no shim between them."""

import energex.analysis.quality as audit
import energex.core.quality as gate


def test_gate_and_audit_are_distinct_modules():
    assert gate.__name__ == "energex.core.quality"
    assert audit.__name__ == "energex.analysis.quality"
    assert gate.__file__ != audit.__file__


def test_gate_exposes_validate_not_dataqualitychecker():
    assert hasattr(gate, "validate")
    assert not hasattr(gate, "DataQualityChecker")


def test_audit_exposes_dataqualitychecker_not_validate():
    assert hasattr(audit, "DataQualityChecker")
    assert not hasattr(audit, "validate")
