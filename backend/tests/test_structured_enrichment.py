from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from app.enrichment.base import (
    EnrichmentBatch,
    EnrichmentCard,
    EnrichmentProvider,
    ProviderUsage,
    persist_profile_batch,
    partition_provider_batch,
    validate_provider_batch,
)
from app.enrichment.openai_provider import (
    MechanicProfileBatchOutput,
    OpenAIEnrichmentProvider,
    _deduplicated_profile,
)
from app.enrichment.pricing import estimate_cost, get_model_prices
from app.enrichment.registry import build_enrichment_provider, provider_is_configured
from app.database import SessionLocal
from app.main import _build_candidate_pool
from app.mechanics.profile import MechanicProfile
from app.models import CardPrinting, InventoryLine, MechanicProfileRecord, OracleCard


def _card() -> EnrichmentCard:
    return EnrichmentCard(
        oracle_id="oracle-sol-ring",
        name="Sol Ring",
        type_line="Artifact",
        mana_cost="{1}",
        oracle_text="{T}: Add {C}{C}.",
        keywords=(),
    )


def _profile(*, confidence: float = 0.99) -> MechanicProfile:
    return MechanicProfile.model_validate({
        "schema_version": "1.0.0",
        "taxonomy_version": "2026.1",
        "oracle_id": "oracle-sol-ring",
        "card_name": "Sol Ring",
        "roles": ["mana_acceleration"],
        "hooks": [{
            "verb": "produces",
            "mechanic": "mana",
            "scope": "self",
            "condition": "tap",
            "evidence": "{T}: Add {C}{C}.",
        }],
        "universal_utility": {
            "tier": "broad",
            "reasons": ["mana_acceleration"],
        },
        "confidence": confidence,
    })


@dataclass
class FakeProvider:
    provider_name: str = "fixture"
    model_name: str = "golden-v1"

    def enrich(self, cards: list[EnrichmentCard]) -> EnrichmentBatch:
        return EnrichmentBatch((_profile(),), ProviderUsage(100, 40))


def test_provider_contract_is_provider_neutral() -> None:
    provider = FakeProvider()
    assert isinstance(provider, EnrichmentProvider)
    batch = provider.enrich([_card()])
    assert validate_provider_batch([_card()], batch) == batch.profiles


def test_openai_enrichment_uses_structured_output_and_exact_oracle_data() -> None:
    captured: dict = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured["request"] = kwargs
            return type("Response", (), {
                "id": "resp_enrichment_test",
                "output_parsed": MechanicProfileBatchOutput(
                    profiles=[_profile().model_dump(mode="json")]
                ),
                "usage": type("Usage", (), {
                    "input_tokens": 150,
                    "output_tokens": 75,
                    "input_tokens_details": type("Details", (), {"cached_tokens": 25})(),
                })(),
            })()

    class FakeClient:
        responses = FakeResponses()

    def client_factory(**kwargs):
        captured["client"] = kwargs
        return FakeClient()

    provider = OpenAIEnrichmentProvider(
        api_key="secret-test-key",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        max_output_tokens_per_card=900,
        timeout_seconds=31,
        max_retries=3,
        client_factory=client_factory,
    )
    batch = provider.enrich([_card()])

    assert batch.profiles == (_profile(),)
    assert batch.usage == ProviderUsage(input_tokens=150, output_tokens=75)
    assert captured["client"] == {
        "api_key": "secret-test-key",
        "timeout": 31,
        "max_retries": 3,
    }
    request = captured["request"]
    assert request["model"] == "gpt-5.6-luna"
    assert request["text_format"] is MechanicProfileBatchOutput
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] == 2_048
    assert request["store"] is False
    payload = json.loads(request["input"])
    assert payload["card_count"] == 1
    assert payload["cards"] == [{
        "oracle_id": "oracle-sol-ring",
        "name": "Sol Ring",
        "type_line": "Artifact",
        "mana_cost": "{1}",
        "oracle_text": "{T}: Add {C}{C}.",
        "scryfall_keywords": [],
    }]
    assert "schema" not in payload


def test_openai_enrichment_returns_empty_batch_without_request() -> None:
    provider = OpenAIEnrichmentProvider(
        api_key="secret-test-key",
        model="gpt-5.6-luna",
        client_factory=lambda **kwargs: pytest.fail("client should not be created"),
    )

    assert provider.enrich([]) == EnrichmentBatch(())


def test_openai_enrichment_configuration_and_cost_lock(monkeypatch, client) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "enrichment_provider", "openai")
    monkeypatch.setattr(settings, "enrichment_model", "gpt-5.6-luna")
    monkeypatch.setattr(settings, "openai_api_key", "secret-test-key")
    monkeypatch.setattr(settings, "openai_requests_enabled", False)

    assert provider_is_configured() is False
    locked = client.post("/api/enrichment/run", json={"batch_size": 1})
    assert locked.status_code == 400
    assert "OPENAI_REQUESTS_ENABLED" in locked.json()["detail"]
    status = client.get("/api/enrichment/status").json()
    assert status["provider_configured"] is False
    assert status["paid_requests_enabled"] is False
    assert status["enrichment_model"] == "gpt-5.6-luna"

    monkeypatch.setattr(settings, "openai_requests_enabled", True)
    assert provider_is_configured() is True
    provider = build_enrichment_provider()
    assert provider.provider_name == "openai"
    assert provider.model_name == "gpt-5.6-luna"


def test_luna_enrichment_cost_estimate_uses_current_configured_prices() -> None:
    assert get_model_prices("openai", "gpt-5.6-luna") == {
        "input": 0.20,
        "output": 1.20,
    }
    assert estimate_cost("openai", "gpt-5.6-luna", 100, 650, 220) == pytest.approx(
        0.0394
    )


def test_closed_schema_rejects_unknown_taxonomy_values_and_fields() -> None:
    data = _profile().model_dump(mode="json")
    data["roles"] = ["made_up_archetype"]
    with pytest.raises(ValidationError):
        MechanicProfile.model_validate(data)


def test_openai_transport_canonicalizes_duplicate_hooks_without_losing_profile() -> None:
    data = _profile().model_dump(mode="json")
    data["hooks"].append(dict(data["hooks"][0]))
    data["roles"].append(data["roles"][0])
    data["universal_utility"]["reasons"].append(
        data["universal_utility"]["reasons"][0]
    )

    transport = MechanicProfileBatchOutput.model_validate({"profiles": [data]})
    profile = _deduplicated_profile(transport.profiles[0])

    assert len(transport.profiles[0].hooks) == 2
    assert profile == _profile()

    data = _profile().model_dump(mode="json")
    data["free_form_tags"] = ["anything_goes"]
    with pytest.raises(ValidationError):
        MechanicProfile.model_validate(data)


def test_provider_validation_rejects_hallucinated_evidence_and_missing_cards() -> None:
    bad = _profile().model_copy(deep=True)
    bad.hooks[0].evidence = "Draw three cards."
    with pytest.raises(ValueError, match="not present"):
        validate_provider_batch([_card()], EnrichmentBatch((bad,)))

    with pytest.raises(ValueError, match="card set mismatch"):
        validate_provider_batch([_card()], EnrichmentBatch(()))


def test_partition_provider_batch_keeps_valid_profiles_and_isolates_bad_evidence() -> None:
    second_card = EnrichmentCard(
        oracle_id="oracle-firja",
        name="Firja, Judge of Valor",
        type_line="Legendary Creature — Angel Cleric",
        mana_cost="{2}{W}{B}{B}",
        oracle_text=(
            "Whenever you cast your second spell each turn, look at the top three cards "
            "of your library. Put one of them into your hand and the rest into your graveyard."
        ),
        keywords=("Flying", "Lifelink"),
    )
    bad = _profile().model_copy(deep=True)
    bad.oracle_id = second_card.oracle_id
    bad.card_name = second_card.name
    bad.hooks[0].evidence = "put the rest into your graveyard."

    valid, failures = partition_provider_batch(
        [_card(), second_card], EnrichmentBatch((_profile(), bad))
    )

    assert valid == (_profile(),)
    assert list(failures) == [second_card.oracle_id]
    assert "not present in Oracle text" in failures[second_card.oracle_id]


def test_persistence_keeps_history_and_one_current_version() -> None:
    with SessionLocal() as db:
        db.add(OracleCard(oracle_id="oracle-sol-ring", name="Sol Ring"))
        db.flush()
        provider = FakeProvider()

        persist_profile_batch(
            db, provider, EnrichmentBatch((_profile(confidence=0.9),), ProviderUsage(101, 41))
        )
        persist_profile_batch(
            db, provider, EnrichmentBatch((_profile(confidence=0.8),), ProviderUsage(99, 39))
        )
        db.commit()

        records = db.query(MechanicProfileRecord).order_by(MechanicProfileRecord.id).all()
        assert len(records) == 2
        assert [record.is_current for record in records] == [False, True]
        assert records[1].provider == "fixture"
        assert records[1].model == "golden-v1"
        assert records[1].input_tokens == 99
        assert records[1].output_tokens == 39


def test_candidate_pool_consumes_current_profile_and_includes_broad_utility() -> None:
    with SessionLocal() as db:
        db.add(OracleCard(
            oracle_id="oracle-sol-ring",
            name="Sol Ring",
            type_line="Artifact",
            oracle_text="{T}: Add {C}{C}.",
            mana_cost="{1}",
            legalities_json='{"commander":"legal"}',
        ))
        db.add(CardPrinting(
            scryfall_id="printing-sol-ring",
            oracle_id="oracle-sol-ring",
        ))
        db.add(InventoryLine(scryfall_id="printing-sol-ring", quantity=1))
        db.flush()
        persist_profile_batch(db, FakeProvider(), EnrichmentBatch((_profile(),)))
        db.commit()

        pool = _build_candidate_pool(db, ["deathtouch"])
        assert [card["name"] for card in pool] == ["Sol Ring"]
        assert pool[0]["mechanic_profile"]["roles"] == ["mana_acceleration"]
        assert pool[0]["mechanic_profile"]["universal_utility"]["tier"] == "broad"


def test_enrichment_api_exposes_versioned_profile_contract(client) -> None:
    status = client.get("/api/enrichment/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["profile_schema_version"] == "1.0.0"
    assert payload["taxonomy_version"] == "2026.1"
    assert "profiled_cards" in payload
    assert "tagged_cards" not in payload

    with SessionLocal() as db:
        db.add(OracleCard(
            oracle_id="oracle-sol-ring",
            name="Sol Ring",
            type_line="Artifact",
            oracle_text="{T}: Add {C}{C}.",
            mana_cost="{1}",
        ))
        db.flush()
        persist_profile_batch(db, FakeProvider(), EnrichmentBatch((_profile(),)))
        db.commit()

    sample = client.get("/api/enrichment/sample?n=1")
    assert sample.status_code == 200
    item = sample.json()[0]
    assert item["profile"]["roles"] == ["mana_acceleration"]
    assert item["provider"] == "fixture"
    assert "synergy_tags" not in item
