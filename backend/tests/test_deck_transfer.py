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


ORACLE_ID = "20000000-0000-4000-8000-000000000001"
PRINTING_A = "20000000-0000-4000-8000-000000000002"
PRINTING_B = "20000000-0000-4000-8000-000000000003"


def _seed_deck() -> int:
    with SessionLocal() as db:
        oracle = OracleCard(
            oracle_id=ORACLE_ID,
            name="Portable Commander",
            type_line="Legendary Creature — Test",
            oracle_text="Vigilance",
            mana_cost="{2}{W}",
            cmc=3,
            colors="W",
            color_identity="W",
            legalities_json='{"commander":"legal"}',
        )
        db.add(oracle)
        db.add_all([
            CardPrinting(
                scryfall_id=PRINTING_A,
                oracle=oracle,
                set_code="one",
                collector_number="1",
                scryfall_json='{"id":"a"}',
            ),
            CardPrinting(
                scryfall_id=PRINTING_B,
                oracle=oracle,
                set_code="two",
                collector_number="2",
                scryfall_json='{"id":"b"}',
            ),
        ])
        db.flush()
        db.add(InventoryLine(
            scryfall_id=PRINTING_A,
            quantity=4,
            foil=False,
            language="en",
        ))
        deck = Deck(
            name="Portable Deck",
            format="commander",
            status="building",
            notes="Keep these notes",
            commander_scryfall_id=PRINTING_A,
            commander_oracle_id=ORACLE_ID,
        )
        db.add(deck)
        db.flush()
        commander = DeckCard(
            deck_id=deck.id,
            scryfall_id=PRINTING_A,
            oracle_id=ORACLE_ID,
            quantity=1,
            grabbed_quantity=1,
            proxy_quantity=0,
            is_commander=True,
            is_sideboard=False,
        )
        sideboard = DeckCard(
            deck_id=deck.id,
            scryfall_id=PRINTING_B,
            oracle_id=ORACLE_ID,
            quantity=2,
            grabbed_quantity=0,
            proxy_quantity=1,
            is_commander=False,
            is_sideboard=True,
        )
        db.add_all([commander, sideboard])
        db.flush()
        db.add_all([
            DeckCardAllocation(
                deck_card_id=commander.id,
                scryfall_id=PRINTING_A,
                status="grabbed",
                quantity=1,
                foil=False,
            ),
            DeckCardAllocation(
                deck_card_id=sideboard.id,
                scryfall_id=PRINTING_B,
                status="proxy",
                quantity=1,
                foil=True,
            ),
            DeckCardAllocation(
                deck_card_id=sideboard.id,
                scryfall_id=None,
                status="pending",
                quantity=1,
                foil=None,
            ),
            MechanicProfileRecord(
                oracle_id=ORACLE_ID,
                schema_version="1",
                taxonomy_version="1",
                profile_json='{"roles":["protection"]}',
                provider="openai",
                model="test-model",
                confidence=0.9,
                is_current=True,
                input_tokens=12,
                output_tokens=6,
            ),
            OracleEmbeddingRecord(
                oracle_id=ORACLE_ID,
                provider="openai",
                model="test-embedding",
                index_version="1",
                dimensions=2,
                source_hash="b" * 64,
                vector=struct.pack("<2f", 0.5, 0.5),
                is_current=True,
                input_tokens=8,
            ),
            RecommendationCardPreference(
                oracle_id=ORACLE_ID,
                accepted_count=3,
                rejected_count=1,
            ),
        ])
        db.commit()
        return deck.id


def test_deck_backup_round_trip_preserves_full_deck_without_changing_collection(
    client: TestClient,
) -> None:
    source_id = _seed_deck()
    exported = client.get(f"/api/decks/{source_id}/export")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("application/gzip")
    payload = json.loads(gzip.decompress(exported.content))
    assert payload["format"] == "spellbinder.deck"
    assert payload["deck"]["notes"] == "Keep these notes"
    assert len(payload["cards"]) == 2
    assert {card["is_sideboard"] for card in payload["cards"]} == {False, True}
    assert len(payload["printings"]) == 2
    assert len(payload["mechanic_profiles"]) == 1
    assert len(payload["embeddings"]) == 1

    preview = client.post(
        "/api/decks/preview-backup",
        files={"file": ("portable-deck.json.gz", exported.content, "application/gzip")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "name": "Portable Deck",
        "format": "commander",
        "status": "building",
        "total_cards": 3,
        "grabbed_cards": 1,
        "proxy_cards": 1,
        "sideboard_cards": 2,
    }

    duplicate_name = client.post(
        "/api/decks/import-backup",
        files={"file": ("portable-deck.json.gz", exported.content, "application/gzip")},
        data={"name": "portable deck", "preserve_positions": "true"},
    )
    assert duplicate_name.status_code == 409

    imported = client.post(
        "/api/decks/import-backup",
        files={"file": ("portable-deck.json.gz", exported.content, "application/gzip")},
        data={"name": "Portable Deck Copy", "preserve_positions": "true"},
    )
    assert imported.status_code == 200, imported.text
    restored = imported.json()
    assert restored["id"] != source_id
    assert restored["name"] == "Portable Deck Copy"
    assert restored["notes"] == "Keep these notes"
    assert restored["commander_scryfall_id"] == PRINTING_A
    assert len(restored["cards"]) == 2
    commander = next(card for card in restored["cards"] if card["is_commander"])
    sideboard = next(card for card in restored["cards"] if card["is_sideboard"])
    assert commander["grabbed_quantity"] == 1
    assert sideboard["proxy_quantity"] == 1
    assert {
        (row["status"], row["scryfall_id"], row["foil"])
        for row in sideboard["allocations"]
    } == {
        ("proxy", PRINTING_B, True),
        ("pending", None, None),
    }

    reset_import = client.post(
        "/api/decks/import-backup",
        files={"file": ("portable-deck.json.gz", exported.content, "application/gzip")},
        data={"name": "Portable Deck Reassembly", "preserve_positions": "false"},
    )
    assert reset_import.status_code == 200, reset_import.text
    reset_cards = reset_import.json()["cards"]
    assert all(card["grabbed_quantity"] == 0 for card in reset_cards)
    assert all(card["proxy_quantity"] == 0 for card in reset_cards)
    assert all(
        allocation["status"] == "pending"
        for card in reset_cards
        for allocation in card["allocations"]
    )
    assert {
        allocation["scryfall_id"]
        for card in reset_cards
        for allocation in card["allocations"]
    } == {PRINTING_A, PRINTING_B, None}

    with SessionLocal() as db:
        assert db.query(InventoryLine).one().quantity == 4
        assert db.query(MechanicProfileRecord).count() == 1
        assert db.query(OracleEmbeddingRecord).count() == 1
        assert db.query(RecommendationCardPreference).count() == 1
