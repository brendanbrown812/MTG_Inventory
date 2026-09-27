from __future__ import annotations

import gzip
import json
import struct

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import (
    CardPrinting,
    Deck,
    DeckCard,
    DeckCardAllocation,
    InventoryLine,
    MechanicProfileRecord,
    OracleCard,
    OracleEmbeddingRecord,
    RecommendationCardPreference,
)


ORACLE_ID = "10000000-0000-4000-8000-000000000001"
SCRYFALL_ID = "10000000-0000-4000-8000-000000000002"


def _seed_portable_collection() -> None:
    with SessionLocal() as db:
        card = OracleCard(
            oracle_id=ORACLE_ID,
            name="Portable Ring",
            type_line="Artifact",
            oracle_text="{T}: Add {C}{C}.",
            mana_cost="{1}",
            cmc=1,
            colors="",
            color_identity="",
            legalities_json='{"commander":"legal"}',
            keywords='["Mana"]',
            synergy_tags='["mana_acceleration"]',
        )
        db.add(card)
        db.add(CardPrinting(
            scryfall_id=SCRYFALL_ID,
            oracle=card,
            set_code="tst",
            collector_number="1",
            rarity="rare",
            language="en",
            image_uri_normal="https://cards.test/portable.jpg",
            scryfall_json='{"id":"portable"}',
        ))
        db.flush()
        db.add(InventoryLine(
            scryfall_id=SCRYFALL_ID,
            quantity=3,
            foil=True,
            condition="near_mint",
            language="en",
            set_code="tst",
            collector_number="1",
            purchase_price=4.25,
            purchase_currency="USD",
            manabox_id="portable-line",
        ))
        db.add(MechanicProfileRecord(
            oracle_id=ORACLE_ID,
            schema_version="1",
            taxonomy_version="1",
            profile_json='{"roles":["ramp"]}',
            provider="openai",
            model="test-model",
            confidence=0.95,
            is_current=True,
            input_tokens=10,
            output_tokens=5,
        ))
        db.add(OracleEmbeddingRecord(
            oracle_id=ORACLE_ID,
            provider="openai",
            model="test-embedding",
            index_version="1",
            dimensions=2,
            source_hash="a" * 64,
            vector=struct.pack("<2f", 0.25, -0.5),
            is_current=True,
            input_tokens=7,
        ))
        db.add(RecommendationCardPreference(
            oracle_id=ORACLE_ID,
            accepted_count=2,
            rejected_count=1,
        ))
        db.commit()


def test_collection_backup_round_trip_is_complete_and_repeat_safe(
    client: TestClient,
) -> None:
    _seed_portable_collection()

    exported = client.get("/api/export/collection")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("application/gzip")
    assert "spellbinder-collection-" in exported.headers["content-disposition"]
    payload = json.loads(gzip.decompress(exported.content))
    assert payload["format"] == "spellbinder.collection"
    assert payload["version"] == 1
    assert payload["inventory_lines"][0]["quantity"] == 3
    assert payload["printings"][0]["scryfall_json"] == '{"id":"portable"}'
    assert payload["mechanic_profiles"][0]["provider"] == "openai"
    assert payload["embeddings"][0]["dimensions"] == 2
    assert payload["card_preferences"][0]["accepted_count"] == 2

    with SessionLocal() as db:
        db.query(InventoryLine).update({InventoryLine.quantity: 99})
        db.query(MechanicProfileRecord).delete()
        db.query(OracleEmbeddingRecord).delete()
        db.query(RecommendationCardPreference).delete()
        db.commit()

    for _ in range(2):
        restored = client.post(
            "/api/import/collection",
            files={"file": (
                "spellbinder-collection.json.gz",
                exported.content,
                "application/gzip",
            )},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json() == {
            "physical_cards": 3,
            "unique_cards": 1,
            "inventory_lines": 1,
            "mechanic_profiles": 1,
            "embeddings": 1,
            "card_preferences": 1,
        }

    with SessionLocal() as db:
        line = db.query(InventoryLine).one()
        assert line.quantity == 3
        assert line.foil is True
        assert line.purchase_price == 4.25
        assert db.query(MechanicProfileRecord).count() == 1
        embedding = db.query(OracleEmbeddingRecord).one()
        assert embedding.vector == struct.pack("<2f", 0.25, -0.5)
        preference = db.query(RecommendationCardPreference).one()
        assert (preference.accepted_count, preference.rejected_count) == (2, 1)


def test_collection_import_rejects_invalid_backup_without_changing_inventory(
    client: TestClient,
) -> None:
    _seed_portable_collection()
    invalid = {
        "format": "spellbinder.collection",
        "version": 1,
        "exported_at": "2026-09-01T12:00:00",
        "oracle_cards": [],
        "printings": [],
        "inventory_lines": [{
            "scryfall_id": SCRYFALL_ID,
            "quantity": 8,
            "foil": False,
        }],
        "mechanic_profiles": [],
        "embeddings": [],
        "card_preferences": [],
    }
    response = client.post(
        "/api/import/collection",
        files={"file": ("invalid.json", json.dumps(invalid), "application/json")},
    )
    assert response.status_code == 400
    with SessionLocal() as db:
        assert db.query(InventoryLine).one().quantity == 3


def test_collection_import_rejects_snapshot_with_too_few_grabbed_cards(
    client: TestClient,
) -> None:
    _seed_portable_collection()
    exported = client.get("/api/export/collection")
    payload = json.loads(gzip.decompress(exported.content))
    payload["inventory_lines"][0]["quantity"] = 1

    with SessionLocal() as db:
        deck = Deck(name="Grabbed Deck", format="commander", status="building")
        db.add(deck)
        db.flush()
        card = DeckCard(
            deck_id=deck.id,
            scryfall_id=SCRYFALL_ID,
            oracle_id=ORACLE_ID,
            quantity=2,
            grabbed_quantity=2,
        )
        db.add(card)
        db.flush()
        db.add(DeckCardAllocation(
            deck_card_id=card.id,
            status="grabbed",
            quantity=2,
            scryfall_id=None,
            foil=None,
        ))
        db.commit()

    response = client.post(
        "/api/import/collection",
        files={"file": ("too-small.json", json.dumps(payload), "application/json")},
    )
    assert response.status_code == 409
    assert "Portable Ring: 2 grabbed, but the snapshot contains 1" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.query(InventoryLine).one().quantity == 3
        assert db.query(DeckCard).one().grabbed_quantity == 2


def test_collection_import_rejects_snapshot_with_wrong_grabbed_treatment(
    client: TestClient,
) -> None:
    _seed_portable_collection()
    exported = client.get("/api/export/collection")
    payload = json.loads(gzip.decompress(exported.content))
    payload["inventory_lines"][0]["foil"] = False

    with SessionLocal() as db:
        deck = Deck(name="Foil Deck", format="commander", status="building")
        db.add(deck)
        db.flush()
        card = DeckCard(
            deck_id=deck.id,
            scryfall_id=SCRYFALL_ID,
            oracle_id=ORACLE_ID,
            quantity=1,
            grabbed_quantity=1,
        )
        db.add(card)
        db.flush()
        db.add(DeckCardAllocation(
            deck_card_id=card.id,
            status="grabbed",
            quantity=1,
            scryfall_id=SCRYFALL_ID,
            foil=True,
        ))
        db.commit()

    response = client.post(
        "/api/import/collection",
        files={"file": ("wrong-treatment.json", json.dumps(payload), "application/json")},
    )
    assert response.status_code == 409
    assert "exact foil printing: 1 grabbed, but the snapshot contains 0" in response.json()["detail"]
    with SessionLocal() as db:
        line = db.query(InventoryLine).one()
        assert line.quantity == 3
        assert line.foil is True


def test_collection_import_preserves_supported_grabbed_allocation(
    client: TestClient,
) -> None:
    _seed_portable_collection()
    exported = client.get("/api/export/collection")

    with SessionLocal() as db:
        deck = Deck(name="Supported Deck", format="commander", status="building")
        db.add(deck)
        db.flush()
        card = DeckCard(
            deck_id=deck.id,
            scryfall_id=SCRYFALL_ID,
            oracle_id=ORACLE_ID,
            quantity=1,
            grabbed_quantity=1,
        )
        db.add(card)
        db.flush()
        db.add(DeckCardAllocation(
            deck_card_id=card.id,
            status="grabbed",
            quantity=1,
            scryfall_id=SCRYFALL_ID,
            foil=True,
        ))
        db.commit()

    response = client.post(
        "/api/import/collection",
        files={"file": ("supported.json.gz", exported.content, "application/gzip")},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.query(InventoryLine).one().quantity == 3
        allocation = db.query(DeckCardAllocation).one()
        assert allocation.status == "grabbed"
        assert allocation.scryfall_id == SCRYFALL_ID
        assert allocation.foil is True
