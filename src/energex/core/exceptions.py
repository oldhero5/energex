"""Custom exceptions for energex."""

import pandas as pd


class EnergexError(Exception):
    """Base exception for all energex errors."""

    pass


class ConfigurationError(EnergexError):
    """Raised when there are configuration issues."""

    pass


class LLMProviderError(EnergexError):
    """Raised when LLM provider operations fail."""

    pass


class DataFetchError(EnergexError):
    """Raised when data fetching operations fail."""

    pass


class AnalysisError(EnergexError):
    """Raised when analysis computations fail."""

    pass


class DatabaseError(EnergexError):
    """Raised when database operations fail."""

    pass


class QualityGateError(EnergexError):
    """Raised by core.quality.validate when a frame fails its pandera schema.

    Carries the schema name and the collected pandera failure_cases so the
    Dagster asset check and CI can surface every failure at once.
    """

    def __init__(self, *, schema_name: str, failures: pd.DataFrame) -> None:
        self.schema_name = schema_name
        self.failures = failures
        super().__init__(
            f"Quality gate failed for schema {schema_name!r}: {len(failures)} failure(s)"
        )


class StorageError(EnergexError):
    """Raised on ArcticDB storage / commit-protocol failures."""


class SymbologyError(EnergexError):
    """Raised when an instrument_id cannot be resolved or its mode is inconsistent."""


class PartitionError(EnergexError):
    """Raised when a Dagster partition key cannot be mapped to a valid_time range."""


class VintageImmutableError(EnergexError):
    """Raised on an attempt to mutate an already-committed live (non-reconstructed) vintage."""
