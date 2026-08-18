"""Application settings. No secrets in source, ever."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="GBA_", extra="ignore"
    )

    environment: str = "development"
    debug: bool = False

    database_url: str = "postgresql+psycopg://gba:gba@localhost:5432/gba"
    redis_url: str = "redis://localhost:6379/0"

    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Outbound collection identity — required by the ethical HTTP client.
    contact_email: str = "changeme@example.invalid"
    public_url: str = "http://localhost:3000/about"

    # Hosts with incomplete TLS chains (audit 6.1). Per-host only, never global.
    tls_exception_hosts: list[str] = Field(default_factory=list)

    rate_limit_per_minute: int = 60
    document_retention_days: int = 90


@lru_cache
def get_settings() -> Settings:
    return Settings()
