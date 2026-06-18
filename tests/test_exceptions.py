"""Tests for the custom exception hierarchy."""

import pandas as pd
import pytest

from energex.core.exceptions import EnergexError as CoreEnergexError
from energex.core.exceptions import QualityGateError
from energex.exceptions import (
    AnalysisError,
    ConfigurationError,
    DatabaseError,
    DataFetchError,
    EnergexError,
    LLMProviderError,
)


@pytest.mark.parametrize(
    "exc",
    [
        ConfigurationError,
        LLMProviderError,
        DataFetchError,
        AnalysisError,
        DatabaseError,
    ],
)
def test_all_custom_errors_subclass_base(exc):
    assert issubclass(exc, EnergexError)


def test_base_is_an_exception():
    assert issubclass(EnergexError, Exception)


def test_specific_error_is_catchable_as_base():
    with pytest.raises(EnergexError):
        raise LLMProviderError("boom")


def test_quality_gate_error_carries_schema_name_and_failures():
    failures = pd.DataFrame(
        {
            "column": ["Open"],
            "check": ["greater_than_or_equal_to(0)"],
            "failure_case": [-1.0],
            "index": [0],
        }
    )
    err = QualityGateError(schema_name="OHLCV", failures=failures)
    assert isinstance(err, CoreEnergexError)
    assert err.schema_name == "OHLCV"
    assert err.failures is failures
    assert "OHLCV" in str(err)
    assert "1" in str(err)  # one failure case reported
