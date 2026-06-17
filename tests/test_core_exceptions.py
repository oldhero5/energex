import pytest

from energex.core.exceptions import (
    EnergexError,
    PartitionError,
    QualityGateError,
    StorageError,
    SymbologyError,
    VintageImmutableError,
)


@pytest.mark.parametrize(
    "exc",
    [QualityGateError, StorageError, SymbologyError, PartitionError, VintageImmutableError],
)
def test_new_exceptions_subclass_base(exc):
    assert issubclass(exc, EnergexError)


def test_quality_gate_error_carries_schema_and_failures():
    err = QualityGateError(schema_name="OHLCV", failures=["row 3: Close < 0"])
    assert err.schema_name == "OHLCV"
    assert err.failures == ["row 3: Close < 0"]
    assert "OHLCV" in str(err)
