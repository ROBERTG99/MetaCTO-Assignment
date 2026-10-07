"""Build the real AI dependencies from settings and config (AI_MODE picks the client)."""

from pathlib import Path

import yaml
from sqlalchemy.engine import Engine

from app.ai.baseline import load_thresholds
from app.ai.embeddings import FastEmbedder
from app.ai.gateway import AnthropicClient, Gateway, LLMClient, OfflineClient, StepConfig, recorder
from app.ai.index import NeedSearch
from app.ai.pipeline import Deps
from app.ai.policy import load_routing
from app.config import get_settings
from app.scoring import load_priorities

CONFIG = Path(__file__).resolve().parents[3] / "config"


def build_deps(engine: Engine, config: Path = CONFIG) -> Deps:
    settings = get_settings()
    routing_file = config / "routing.yaml"
    llm = yaml.safe_load(routing_file.read_text(encoding="utf-8"))["llm"]
    model = {"fast": settings.fast_model, "smart": settings.smart_model}
    live = settings.ai_mode == "live"
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    client: LLMClient = (
        AnthropicClient(settings.llm_timeout_seconds, settings.llm_max_retries, api_key=key)
        if live
        else OfflineClient()
    )
    priorities = load_priorities(config / "priorities.yaml")
    steps = {
        "extract": StepConfig(model[llm["models"]["extract"]] if live else "offline-baseline", 2000),
        "adjudicate": StepConfig(
            model[llm["models"]["adjudicate"]], 4000, llm.get("effort", {}).get("adjudicate")
        ),
        "strategic_fit": StepConfig(model[priorities.fit_model], 1500),
    }
    prices = yaml.safe_load((config / "prices.yaml").read_text(encoding="utf-8"))
    gateway = Gateway(client=client, steps=steps, prices=prices, record=recorder(engine))
    return Deps(
        gateway=gateway,
        search=NeedSearch(FastEmbedder()),
        routing=load_routing(routing_file),
        priorities=priorities,
        mode="llm" if live else "baseline",
        baseline=load_thresholds(routing_file),
    )
