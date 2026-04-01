"""Application settings — all env-driven configuration for the API layer."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API, database, Redis, and CORS settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/app.db",
        description="Async SQLAlchemy URL for task persistence",
    )
    redis_url: str | None = Field(
        default="redis://127.0.0.1:6379/0",
        description="Redis URL for response cache; empty disables Redis",
    )
    redis_optional: bool = Field(
        default=True,
        description="If True, API runs when Redis is unreachable (cache miss only)",
    )
    api_key: str | None = Field(
        default=None,
        description="If set, require X-API-Key header on task routes",
    )
    cache_ttl_seconds: int = Field(default=3600, ge=60)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    api_v1_prefix: str = "/api/v1"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("redis_url", mode="before")
    @classmethod
    def empty_redis_url(cls, v: str | None) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
