"""Custom exceptions for energex."""


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
