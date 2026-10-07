"""The test-only provider fault (e2e "provider failure" path): off unless APP_ENV=test, and only for marked text."""

import pytest

from app.ai.gateway import FaultInjectingClient, OfflineClient, TerminalError
from app.ai.schemas import Extraction


def call(client: object, text: str) -> object:
    return client.complete(step="extract", model="offline-baseline", system="", user="", schema=Extraction,  # type: ignore[attr-defined]
                           max_tokens=1, effort=None, inputs={"text": text, "role": "Owner"})  # fmt: skip


def test_marked_text_fails_like_a_provider_refusal() -> None:
    client = FaultInjectingClient(OfflineClient())
    with pytest.raises(TerminalError, match="simulated provider failure"):
        call(client, "Payroll export [simulate-provider-failure]")


def test_unmarked_text_goes_through() -> None:
    reply = call(FaultInjectingClient(OfflineClient()), "Dark mode")
    assert reply.output.need_statement == "Dark mode"  # type: ignore[attr-defined]


@pytest.mark.parametrize(("env", "wrapped"), [("test", True), ("production", False), ("development", False)])
def test_the_fault_switch_exists_only_in_the_test_environment(
    monkeypatch: pytest.MonkeyPatch, env: str, wrapped: bool
) -> None:
    from app.ai import factory
    from app.config import get_settings

    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("AI_MODE", "offline")
    get_settings.cache_clear()
    try:
        client = factory.make_client(get_settings())
    finally:
        get_settings.cache_clear()
    assert isinstance(client, FaultInjectingClient) is wrapped
