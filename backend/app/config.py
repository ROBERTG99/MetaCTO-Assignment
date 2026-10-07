"""Application settings, read from the environment (and a local .env, which is never committed)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # the repo-root .env (next to .env.example), then backend/.env; real environment variables win over both
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "sqlite:///./data/distill.db"
    ai_mode: Literal["offline", "live"] = "offline"
    anthropic_api_key: SecretStr | None = None  # from the environment or .env; never logged
    fast_model: str = "claude-haiku-4-5"
    smart_model: str = "claude-sonnet-5-5"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ".cache/fastembed"  # relative to backend/; filled by make setup
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2  # SDK-level retries for 408/409/429/5xx; the worker adds its own (3 attempts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
