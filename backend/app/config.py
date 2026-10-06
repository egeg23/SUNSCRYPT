from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables prefixed SUNS_ (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="SUNS_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    version: str = "0.1.0"
    database_url: str = "postgresql+asyncpg://sunscrypt:sunscrypt@localhost:5432/sunscrypt"
    redis_url: str = "redis://localhost:6379/0"
    # Registration starts invite-only; flip to "open" when the service goes public.
    registration: Literal["invite", "open"] = "invite"
    # Real-money trading is off for the whole service until the owner turns it on.
    live_trading_enabled: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
