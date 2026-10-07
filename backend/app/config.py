"""Application settings, read from the environment (and a local .env, which is never committed)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/distill.db"
    ai_mode: Literal["offline", "live"] = "offline"
    fast_model: str = "claude-haiku-4-5"
    smart_model: str = "claude-sonnet-5-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
