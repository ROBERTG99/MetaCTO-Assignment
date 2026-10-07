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
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ".cache/fastembed"  # relative to backend/; filled by make setup


@lru_cache
def get_settings() -> Settings:
    return Settings()
