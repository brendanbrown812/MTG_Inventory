from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models import CardPrinting, InventoryLine, OracleCard
from app.review.base import (
    REVIEW_SCHEMA_VERSION,
    CardRecommendation,
    SuggestReview,
    validate_audit_review,
    AuditReview,
    ReplacementRecommendation,
)
from app.review.deterministic_provider import DeterministicDeckReviewer
from app.review.openai_provider import OpenAIDeckReviewer
from app.review.registry import FallbackDeckReviewer


def _owned_card(
    db,
    oracle_id: str,
    name: str,
    *,
    oracle_text: str,
    cmc: float,
    type_line: str = "Creature",
) -> None:
    db.add(OracleCard(
        oracle_id=oracle_id,
        name=name,
        type_line=type_line,
        oracle_text=oracle_text,
        cmc=cmc,
        legalities_json=json.dumps({"commander": "legal"}),
        keywords="[]",
    ))
    db.add(CardPrinting(scryfall_id=f"printing-{oracle_id}", oracle_id=oracle_id))
    db.add(InventoryLine(scryfall_id=f"printing-{oracle_id}", quantity=1))


def _candidate(name: str = "Useful Insight") -> dict:
    return {
        "name": name,
        "mana_cost": "{2}{U}",
        "cmc": 3,
        "type_line": "Instant",
        "oracle_text": "Draw two cards.",
        "color_identity": '["U"]',
        "owned_quantity": 1,
        "deterministic_roles": ["card_draw"],
        "mechanic_profile": None,
        "retrieval": {
            "total_score": 18.0,
            "components": {"semantic": 12.0, "functional_role": 6.0},
            "reasons": ["Fills missing deck function: card_advantage"],
        },
    }


def test_openai_suggest_uses_strict_output_and_bounded_payload() -> None:
    request: dict = {}
    parsed = SuggestReview(
        theme_assessment="The list needs more card flow.",
        suggestions=[CardRecommendation(name="Useful Insight", reason="Adds card flow.")],
        cards_to_consider_cutting=[
            CardRecommendation(name="Slow Giant", reason="The curve is top-heavy.")
        ],
        viability_note="The owned pool supports the plan.",
    )

    class FakeResponses:
        def parse(self, **kwargs):
            request.update(kwargs)
            return SimpleNamespace(
                id="resp_review",
                output_parsed=parsed,
                usage=SimpleNamespace(input_tokens=200, output_tokens=80),
            )

    reviewer = OpenAIDeckReviewer(
        "test-key",
        "gpt-5.6-luna",
        client_factory=lambda **_: SimpleNamespace(responses=FakeResponses()),
    )
    result = reviewer.suggest(
        "1 Slow Giant",
        [_candidate()],
        "card advantage",
        [{
            "name": "Slow Giant", "quantity": 1, "cmc": 8,
            "type_line": "Creature", "oracle_text": "", "deterministic_roles": [],
        }],
    )

    assert result.suggestions[0].name == "Useful Insight"
    assert request["model"] == "gpt-5.6-luna"
    assert request["text_format"] is SuggestReview
    assert request["store"] is False
    assert request["reasoning"] == {"effort": "low"}
    payload = json.loads(request["input"])
    assert payload["current_deck_names"] == ["Slow Giant"]
    assert [card["name"] for card in payload["candidate_additions"]] == ["Useful Insight"]


def test_review_validation_rejects_hallucinated_cards_and_replacements() -> None:
    review = AuditReview(
        overall_assessment="Needs work.",
        strategy_assessment="The plan is inconsistent.",
        suggested_cuts=[CardRecommendation(name="Slow Giant", reason="Expensive.")],
        suggested_additions=[
            ReplacementRecommendation(
                name="Card That Is Not Owned", replaces="Slow Giant", reason="Imaginary upgrade."
            )
        ],
    )
    with pytest.raises(ValueError, match="outside the candidate pool"):
        validate_audit_review([_candidate()], ["Slow Giant"], review)

    bad_replacement = review.model_copy(update={
        "suggested_additions": [ReplacementRecommendation(
            name="Useful Insight", replaces="Imaginary Cut", reason="Invalid replacement."
        )]
    })
    with pytest.raises(ValueError, match="outside the current deck"):
        validate_audit_review([_candidate()], ["Slow Giant"], bad_replacement)


def test_reviewer_falls_back_when_optional_provider_fails() -> None:
    class BrokenReviewer:
        provider_name = "openai"
        model_name = "broken"

        def suggest(self, *args):
            raise RuntimeError("provider unavailable")

        def audit(self, *args):
            raise RuntimeError("provider unavailable")

    reviewer = FallbackDeckReviewer(BrokenReviewer(), DeterministicDeckReviewer())
    result = reviewer.suggest("1 Slow Giant", [_candidate()], None, [])
    assert reviewer.provider_name == "deterministic"
    assert result.schema_version == REVIEW_SCHEMA_VERSION
    assert result.suggestions[0].name == "Useful Insight"


def test_suggest_and_audit_work_without_anthropic_or_paid_openai(client, monkeypatch) -> None:
    with SessionLocal() as db:
        _owned_card(
            db, "oracle-slow", "Slow Giant", oracle_text="Vanilla threat.", cmc=8,
        )
        _owned_card(
            db, "oracle-insight", "Useful Insight", oracle_text="Draw two cards.",
            cmc=3, type_line="Instant",
        )
        db.commit()

    from app.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openai_requests_enabled", False)
    monkeypatch.setattr(settings, "review_provider", "openai")

    suggested = client.post("/api/deckbuilding/suggest", json={
        "current_list": "1 Slow Giant",
        "theme_hint": "card advantage",
    })
    assert suggested.status_code == 200, suggested.text
    suggestion_payload = suggested.json()
    assert suggestion_payload["result"]["review_provenance"] == {
        "provider": "deterministic",
        "model": "rules-v1",
        "schema_version": REVIEW_SCHEMA_VERSION,
    }
    assert suggestion_payload["result"]["suggestions"][0]["name"] == "Useful Insight"

    audited = client.post("/api/deckbuilding/audit", json={
        "decklist": "1 Slow Giant",
    })
    assert audited.status_code == 200, audited.text
    audit_payload = audited.json()
    assert audit_payload["result"]["review_provenance"]["provider"] == "deterministic"
    assert audit_payload["result"]["suggested_additions"][0]["name"] == "Useful Insight"
    assert audit_payload["result"]["suggested_cuts"][0]["name"] == "Slow Giant"
    assert audit_payload["warnings"]
