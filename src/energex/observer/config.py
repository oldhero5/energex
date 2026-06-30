"""Observer API settings (env: OBSERVER_*). Holds the Supabase JWT secret + CORS + arctic uri."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObserverSettings(BaseSettings):
    jwt_secret: SecretStr = Field(validation_alias="OBSERVER_JWT_SECRET")
    cors_origins: str = Field(default="", validation_alias="OBSERVER_CORS_ORIGINS")
    jwt_audience: str = Field(default="authenticated", validation_alias="OBSERVER_JWT_AUDIENCE")

    model_config = SettingsConfigDict(case_sensitive=False)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
