"""Tests for the custom exception hierarchy."""

import pytest

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
