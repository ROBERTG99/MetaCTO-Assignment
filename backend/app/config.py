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
    app_env: Literal["development", "test", "production"] = "development"  # test enables the e2e fault switch
    anthropic_api_key: SecretStr | None = None  # from the environment or .env; never logged
    fast_model: str = "claude-haiku-4-5"
    smart_model: str = "claude-sonnet-5-5"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ".cache/fastembed"  # relative to backend/; filled by make setup
    llm_timeout_seconds: float = 30.0
    # Production limits (README "Production path"): browser origins allowed by CORS, public write rate per
    # client, request body cap, and log format (json for production, text for reading locally).
    web_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:5174"
    posts_per_minute: int = 30
    writes_per_minute: int = 120
    daily_model_budget_usd: float = (
        20.0  # the worker stops claiming jobs once today's model spend reaches this
    )
    docs_enabled: bool = True
    max_body_bytes: int = 64_000
    log_format: str = "json"
    llm_max_retries: int = 2  # SDK-level retries for 408/409/429/5xx; the worker adds its own (3 attempts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
