"""Configuration management for energex using Pydantic settings."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from energex.core.exceptions import ConfigurationError


class LLMConfig(BaseSettings):
    """LLM provider configuration."""

    provider: Literal["openai", "anthropic", "ollama"] = Field(
        default="openai", description="LLM provider to use"
    )
    model: str = Field(default="gpt-4", description="Model name for the chosen provider")
    api_key: SecretStr | None = Field(default=None, description="API key for the LLM provider")
    base_url: str | None = Field(default=None, description="Base URL for local LLM (Ollama)")
    requests_per_minute: int = Field(
        default=10, description="Maximum API requests per minute", gt=0
    )
    cache_ttl: int = Field(default=3600, description="Cache TTL for LLM responses in seconds", ge=0)

    # Distinct prefix (was env_prefix="" which bound bare API_KEY/MODEL/BASE_URL and
    # leaked foreign env vars into this config). validate_assignment re-checks overrides
    # applied by EnergexSettings.model_post_init (e.g. an invalid provider).
    model_config = SettingsConfigDict(
        env_prefix="LLM_", case_sensitive=False, validate_assignment=True
    )


class NewsConfig(BaseSettings):
    """News API configuration."""

    news_api_key: SecretStr | None = Field(
        default=None, description="NewsAPI.org API key (env: NEWS_API_KEY)"
    )
    alpha_vantage_key: SecretStr | None = Field(
        default=None, description="Alpha Vantage API key (env: ALPHA_VANTAGE_KEY)"
    )

    # env_prefix="" with descriptive field names gives the intuitive NEWS_API_KEY /
    # ALPHA_VANTAGE_KEY (the previous NEWS_ prefix required NEWS_NEWS_API_KEY).
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)


class LegacyDuckDBConfig(BaseSettings):
    """Legacy DuckDB path config (read path / existing tests). Reached via the
    `settings.database` property alias; preserved while core config grows
    ArcticDB/Neo4j/Connector sections in S1 phase 1."""

    db_path: Path = Field(default=Path("energy.db"), description="Path to DuckDB database")

    model_config = SettingsConfigDict(env_prefix="ENERGEX_", case_sensitive=False)

    @field_validator("db_path", mode="before")
    @classmethod
    def validate_db_path(cls, v: str | Path) -> Path:
        """Convert string to Path."""
        return Path(v) if isinstance(v, str) else v


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str | None = Field(default=None, description="Path to log file")
    log_enable_console: bool = Field(default=True, description="Enable console logging")

    model_config = SettingsConfigDict(env_prefix="LOG_", case_sensitive=False)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ConfigurationError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v_upper


class DataFetchConfig(BaseSettings):
    """Data fetching configuration."""

    yfinance_timeout: int = Field(default=30, description="Yahoo Finance timeout in seconds")
    data_fetch_retries: int = Field(default=3, description="Number of download attempts", ge=0)
    dated_enabled: bool = Field(
        default=True, description="Enable ingestion of the dated futures contract strip"
    )
    dated_lookback_days: int = Field(
        default=45, description="Daily-bar lookback window per dated contract", ge=1
    )
    dated_contract_count: int = Field(
        default=12, description="Number of forward monthly contracts to fetch per commodity", ge=1
    )

    model_config = SettingsConfigDict(env_prefix="DATAFETCH_", case_sensitive=False)


class AnalysisConfig(BaseSettings):
    """Analysis configuration."""

    sentiment_default_hours_back: int = Field(
        default=24, description="Default hours for sentiment analysis", gt=0
    )
    sentiment_confidence_threshold: float = Field(
        default=0.5, description="Minimum confidence threshold", ge=0.0, le=1.0
    )

    model_config = SettingsConfigDict(env_prefix="SENTIMENT_", case_sensitive=False)


class ArcticDBConfig(BaseSettings):
    """ArcticDB-on-MinIO storage config (env: MINIO_* / ARCTIC_*)."""

    minio_endpoint: str = Field(default="localhost:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: SecretStr | None = Field(default=None, validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: SecretStr | None = Field(default=None, validation_alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="arctic", validation_alias="ARCTIC_BUCKET")
    arctic_secure: bool = Field(default=False, validation_alias="ARCTIC_SECURE")

    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)


class Neo4jConfig(BaseSettings):
    """Neo4j entity-graph config (env: NEO4J_*)."""

    uri: str = Field(default="bolt://localhost:7687", description="env: NEO4J_URI")
    user: str = Field(default="neo4j", description="env: NEO4J_USER")
    password: SecretStr | None = Field(default=None, description="env: NEO4J_PASSWORD")

    model_config = SettingsConfigDict(env_prefix="NEO4J_", case_sensitive=False)


class ConnectorConfig(BaseSettings):
    """Source connector credentials (env: EIA_API_KEY, FRED_API_KEY, ERCOT_*, NOAA_TOKEN)."""

    eia_api_key: SecretStr | None = Field(default=None, validation_alias="EIA_API_KEY")
    fred_api_key: SecretStr | None = Field(default=None, validation_alias="FRED_API_KEY")
    ercot_username: str | None = Field(default=None, validation_alias="ERCOT_USERNAME")
    ercot_password: SecretStr | None = Field(default=None, validation_alias="ERCOT_PASSWORD")
    ercot_subscription_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ERCOT_API_KEY_PRIMARY", "ERCOT_SUBSCRIPTION_KEY"),
    )
    ercot_subscription_key_secondary: SecretStr | None = Field(
        default=None, validation_alias="ERCOT_API_KEY_SECONDARY"
    )
    noaa_token: SecretStr | None = Field(default=None, validation_alias="NOAA_TOKEN")

    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)


class EnergexSettings(BaseSettings):
    """Main application settings."""

    # Sub-configurations
    llm: LLMConfig = Field(default_factory=LLMConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    legacy_db: LegacyDuckDBConfig = Field(default_factory=LegacyDuckDBConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    data_fetch: DataFetchConfig = Field(default_factory=DataFetchConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    arctic: ArcticDBConfig = Field(default_factory=ArcticDBConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    connectors: ConnectorConfig = Field(default_factory=ConnectorConfig)

    # Override for specific settings
    default_llm_provider: str | None = Field(
        default=None, description="Override for default LLM provider"
    )
    default_llm_model: str | None = Field(
        default=None, description="Override for default LLM model"
    )
    openai_api_key: SecretStr | None = Field(default=None, description="OpenAI API key")
    anthropic_api_key: SecretStr | None = Field(default=None, description="Anthropic API key")
    ollama_base_url: str | None = Field(default=None, description="Ollama base URL")
    llm_requests_per_minute: int | None = Field(default=None, description="LLM requests per minute")
    llm_cache_ttl_seconds: int | None = Field(default=None, description="LLM cache TTL")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    def model_post_init(self, __context: object) -> None:
        """Apply top-level overrides to the LLM sub-config (validated on assignment)."""
        if self.default_llm_provider is not None:
            self.llm.provider = self.default_llm_provider  # type: ignore[assignment]
        if self.default_llm_model is not None:
            self.llm.model = self.default_llm_model
        if self.llm_requests_per_minute is not None:
            self.llm.requests_per_minute = self.llm_requests_per_minute
        if self.llm_cache_ttl_seconds is not None:
            self.llm.cache_ttl = self.llm_cache_ttl_seconds

        # Set the API key / base URL for the active provider.
        if self.llm.provider == "openai" and self.openai_api_key is not None:
            self.llm.api_key = self.openai_api_key
        elif self.llm.provider == "anthropic" and self.anthropic_api_key is not None:
            self.llm.api_key = self.anthropic_api_key
        elif self.llm.provider == "ollama" and self.ollama_base_url is not None:
            self.llm.base_url = self.ollama_base_url

    @property
    def database(self) -> LegacyDuckDBConfig:
        """Back-compat alias preserving `settings.database.db_path`. Kept as a
        property (not a field) so future core config sections can be added
        alongside it without changing this read path."""
        return self.legacy_db


# Singleton pattern for settings
_settings: EnergexSettings | None = None


def get_settings(reload: bool = False) -> EnergexSettings:
    """
    Get or create the global settings instance.

    Args:
        reload: If True, reload settings from environment. Defaults to False.

    Returns:
        The global EnergexSettings instance.

    Example:
        >>> settings = get_settings()
        >>> print(settings.llm.provider)
        openai
    """
    global _settings
    if _settings is None or reload:
        _settings = EnergexSettings()
    return _settings


def reset_settings() -> None:
    """Reset the global settings instance. Useful for testing."""
    global _settings
    _settings = None
