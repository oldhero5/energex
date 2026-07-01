"""Observer API settings (env: OBSERVER_*). Holds the Supabase JWT secret + arctic uri."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObserverSettings(BaseSettings):
    jwt_secret: SecretStr = Field(validation_alias="OBSERVER_JWT_SECRET")
    jwt_audience: str = Field(default="authenticated", validation_alias="OBSERVER_JWT_AUDIENCE")
    supabase_url: str | None = Field(default=None, validation_alias="SUPABASE_URL")
    supabase_service_key: SecretStr | None = Field(
        default=None, validation_alias="SUPABASE_SERVICE_KEY"
    )
    dagster_graphql_url: str = Field(
        default="http://dagster-webserver:3000/graphql", validation_alias="DAGSTER_GRAPHQL_URL"
    )

    model_config = SettingsConfigDict(case_sensitive=False)
