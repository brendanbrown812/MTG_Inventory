from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from app.enrichment.base import (
    EnrichmentBatch,
    EnrichmentCard,
    EnrichmentProvider,
    ProviderUsage,
    persist_profile_batch,
    validate_provider_batch,
)
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


def test_closed_schema_rejects_unknown_taxonomy_values_and_fields() -> None:
    data = _profile().model_dump(mode="json")
    data["roles"] = ["made_up_archetype"]
    with pytest.raises(ValidationError):
        MechanicProfile.model_validate(data)

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
