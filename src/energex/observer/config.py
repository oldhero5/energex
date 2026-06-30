"""Observer API settings (env: OBSERVER_*). Holds the Supabase JWT secret + arctic uri."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObserverSettings(BaseSettings):
    jwt_secret: SecretStr = Field(validation_alias="OBSERVER_JWT_SECRET")
    jwt_audience: str = Field(default="authenticated", validation_alias="OBSERVER_JWT_AUDIENCE")

    model_config = SettingsConfigDict(case_sensitive=False)
