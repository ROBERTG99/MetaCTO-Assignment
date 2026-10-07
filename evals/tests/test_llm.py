"""The LLM eval's own logic, with no client: the dev replay's per-item backlog and the routing of one item."""

import json
from pathlib import Path
from typing import Any

import pytest
from app.ai.embeddings import FakeEmbedder
from app.ai.policy import RoutingConfig
from app.ai.retrieval import NeedIndex
from app.ai.schemas import Adjudication, Extraction, Judgment
from app.models import Need

import evals.llm as L


def extraction(statement: str, persona: str = "it_admin", area: Any = "security_admin") -> Extraction:
    return Extraction(need_statement=statement, problem=statement, persona=persona, job_to_be_done="j",
                      proposed_solution="s", product_area=area, severity_signal="unknown", evidence=[],
                      confidence=0.9, rationale="r")  # fmt: skip


@pytest.fixture
def seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    requests = [
        {"ref": "R1", "title": "SSO with Okta", "description": "okta single sign on", "requester": "a"},
        {
            "ref": "R2",
            "title": "Okta login please",
            "description": "okta single sign on for staff",
            "requester": "a",
        },
        {
            "ref": "R3",
            "title": "SAML for Okta",
            "description": "single sign on with okta saml",
            "requester": "a",
        },
    ]
    truth = {"needs": {"sso": {"title": "IT admins need SSO", "persona": "it_admin", "product_area": "security_admin"}},
             "requests": {r["ref"]: {"need": "sso"} for r in requests}, "arrival_order": ["R1", "R2", "R3"]}  # fmt: skip
    (tmp_path / "requests.json").write_text(json.dumps(requests))
    (tmp_path / "ground_truth.json").write_text(json.dumps(truth))
    monkeypatch.setattr(L, "SEED", tmp_path)
    return tmp_path


def test_a_dev_item_never_sees_its_own_or_a_later_title(seed: Path) -> None:
    exs = {r: extraction("IT admins need SSO") for r in ("R1", "R2", "R3")}
    items, _needs, _examples = L.dev_items(lambda: NeedIndex(FakeEmbedder()), exs)
    by_ref = {it.ref: it for it in items}
    assert by_ref["R1"].examples == {}  # nothing has arrived yet
    assert by_ref["R2"].examples == {"sso": ["SSO with Okta"]}  # only R1, never R2 itself
    assert by_ref["R3"].examples == {"sso": ["SSO with Okta", "Okta login please"]}


def test_a_dev_item_whose_first_extraction_failed_is_skipped_not_a_crash(seed: Path) -> None:
    items, needs, _ = L.dev_items(
        lambda: NeedIndex(FakeEmbedder()), {"R2": extraction("x"), "R3": extraction("x")}
    )
    assert [it.ref for it in items] == ["R1", "R2", "R3"]
    assert "sso" in needs  # born from the first request that has an extraction


def test_route_one_uses_the_apps_routing() -> None:
    needs = {"sso": Need(id=1, title="IT admins need SSO", problem="p", persona="it_admin", product_area="security_admin"),
             "dark": Need(id=2, title="Users want dark mode", problem="p", persona="end_user", product_area="ui")}  # fmt: skip
    item = L.Item(
        "X", "test", "okta sso", "IT Director", "sso", ["paraphrase"], [("sso", 0.95), ("dark", 0.3)]
    )
    adj = Adjudication(judgments=[Judgment(candidate_id="1", label="same_need", confidence=0.9, rationale="r", quotes=[]),
                                  Judgment(candidate_id="2", label="related", confidence=0.6, rationale="r", quotes=[])])  # fmt: skip
    cfg = RoutingConfig(s_min=0.2, s_max=0.8)
    band, predicted, score, top, top_score, labels = L.route_one(item, extraction("x"), adj, needs, cfg)
    assert (band, predicted, top, labels) == ("auto", "sso", "sso", {"sso": "same_need", "dark": "related"})
    assert score == top_score == pytest.approx(1.0)
