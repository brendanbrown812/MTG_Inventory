from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.models import CardPrinting, InventoryLine, OracleCard


SCRYFALL_ID = "00000000-0000-4000-8000-000000000001"
SECOND_PRINTING_ID = "00000000-0000-4000-8000-000000000003"


def _add_cached_card() -> None:
    with SessionLocal() as db:
        oracle = OracleCard(
            oracle_id="00000000-0000-4000-8000-000000000002",
            name="Test Ring",
            type_line="Artifact",
            oracle_text="{T}: Add {C}{C}.",
            mana_cost="{1}",
            cmc=1,
            colors="",
            color_identity="",
            legalities_json='{"commander": "legal"}',
        )
        db.add(oracle)
        db.add(CardPrinting(
            scryfall_id=SCRYFALL_ID,
            oracle=oracle,
            rarity="rare",
        ))
        db.commit()


def test_health_and_empty_status(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"ok": True}
    status = client.get("/api/enrichment/status")
    assert status.status_code == 200
    assert status.json()["total_cards"] == 0


def test_api_key_protects_private_routes(client: TestClient) -> None:
    settings.app_api_key = "test-secret"

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").json() == {
        "required": True,
        "authenticated": False,
    }
    assert client.get("/api/inventory").status_code == 401
    assert client.get(
        "/api/inventory",
        headers={"X-Spellbinder-Key": "wrong"},
    ).status_code == 401
    assert client.get(
        "/api/inventory",
        headers={"X-Spellbinder-Key": "test-secret"},
    ).status_code == 200


def test_inventory_listing_and_clear(client: TestClient) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        db.add(InventoryLine(
            scryfall_id=SCRYFALL_ID,
            quantity=2,
            foil=False,
            language="en",
        ))
        db.commit()

    rows = client.get("/api/inventory").json()
    assert len(rows) == 1
    assert rows[0]["quantity"] == 2
    assert rows[0]["card"]["name"] == "Test Ring"

    result = client.post("/api/inventory/clear")
    assert result.status_code == 200
    assert result.json() == {"deleted": 1}
    assert client.get("/api/inventory").json() == []


def test_manabox_import_merges_cached_card(client: TestClient) -> None:
    _add_cached_card()
    csv_text = (
        "Name,Scryfall ID,Quantity,Foil,Condition,Language\n"
        f"Test Ring,{SCRYFALL_ID},2,false,near_mint,en\n"
        f"Test Ring,{SCRYFALL_ID},1,false,near_mint,en\n"
    )

    response = client.post(
        "/api/import/manabox?import_key=test-import",
        files={"file": ("collection.csv", csv_text, "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["added_quantity"] == 3

    rows = client.get("/api/inventory").json()
    assert len(rows) == 1
    assert rows[0]["quantity"] == 3


def test_manabox_import_uses_stale_local_printing_without_scryfall(
    client: TestClient,
    monkeypatch,
) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        printing = db.get(CardPrinting, SCRYFALL_ID)
        printing.updated_at = datetime(2000, 1, 1)
        db.commit()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("A cached collection printing should not be refetched")

    monkeypatch.setattr(
        "app.services.scryfall_client.ScryfallClient.fetch_cards_collection",
        fail_if_called,
    )
    csv_text = (
        "Name,Scryfall ID,Quantity,Foil,Condition,Language\n"
        f"Test Ring,{SCRYFALL_ID},1,false,near_mint,en\n"
    )
    response = client.post(
        "/api/import/manabox?import_key=stale-cache",
        files={"file": ("collection.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["added_quantity"] == 1
    assert client.get("/api/inventory").json()[0]["quantity"] == 1


def test_manabox_import_hydrates_two_printings_of_one_oracle(
    client: TestClient,
    monkeypatch,
) -> None:
    shared_oracle_id = "30000000-0000-4000-8000-000000000001"
    printing_ids = [
        "30000000-0000-4000-8000-000000000002",
        "30000000-0000-4000-8000-000000000003",
    ]

    def fetch_shared_printings(_client, requested_ids):
        assert requested_ids == printing_ids
        return [
            {
                "id": printing_id,
                "oracle_id": shared_oracle_id,
                "name": "Shared Oracle Test",
                "type_line": "Artifact",
                "cmc": 2,
                "set": f"t{index}",
                "collector_number": str(index),
                "legalities": {"commander": "legal"},
            }
            for index, printing_id in enumerate(printing_ids, start=1)
        ], []

    monkeypatch.setattr(
        "app.services.scryfall_client.ScryfallClient.fetch_cards_collection",
        fetch_shared_printings,
    )
    csv_text = (
        "Name,Scryfall ID,Quantity,Foil,Condition,Language\n"
        f"Shared Oracle Test,{printing_ids[0]},1,false,near_mint,en\n"
        f"Shared Oracle Test,{printing_ids[1]},1,false,near_mint,en\n"
    )
    response = client.post(
        "/api/import/manabox?import_key=shared-oracle",
        files={"file": ("collection.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.query(OracleCard).filter(
            OracleCard.oracle_id == shared_oracle_id
        ).count() == 1
        assert db.query(CardPrinting).filter(
            CardPrinting.oracle_id == shared_oracle_id
        ).count() == 2


def test_manabox_import_reports_hydration_failure_and_keeps_progress(
    client: TestClient,
    monkeypatch,
) -> None:
    csv_text = (
        "Name,Scryfall ID,Quantity\n"
        f"Test Ring,{SCRYFALL_ID},1\n"
    )

    def fail_hydration(*_args, **_kwargs):
        raise RuntimeError("simulated cache failure")

    monkeypatch.setattr("app.main.bulk_ensure_cards_cached", fail_hydration)
    response = client.post(
        "/api/import/manabox?import_key=failing-import",
        files={"file": ("collection.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 500
    assert "hydrating_cards" in response.json()["detail"]
    progress = client.get(
        "/api/import/manabox/progress?import_key=failing-import"
    ).json()
    assert progress["status"] == "failed"
    assert progress["stage"] == "hydrating_cards"
    assert "simulated cache failure" in progress["error"]


def test_manabox_import_survives_optional_deck_matching_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    _add_cached_card()
    csv_text = (
        "Name,Scryfall ID,Quantity,Foil,Condition,Language\n"
        f"Test Ring,{SCRYFALL_ID},2,false,near_mint,en\n"
    )

    def fail_matching(*_args, **_kwargs):
        raise RuntimeError("simulated matcher failure")

    monkeypatch.setattr("app.main.match_new_cards", fail_matching)
    response = client.post(
        "/api/import/manabox?import_key=matcher-failure",
        files={"file": ("collection.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["added_quantity"] == 2
    assert client.get("/api/inventory").json()[0]["quantity"] == 2
    progress = client.get(
        "/api/import/manabox/progress?import_key=matcher-failure"
    ).json()
    assert progress["status"] == "complete"


def test_deck_merges_printings_of_the_same_oracle_card(client: TestClient) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        oracle = db.get(OracleCard, "00000000-0000-4000-8000-000000000002")
        db.add(CardPrinting(
            scryfall_id=SECOND_PRINTING_ID,
            oracle=oracle,
            rarity="uncommon",
        ))
        db.commit()

    response = client.post("/api/decks", json={
        "name": "Oracle identity deck",
        "cards": [
            {"scryfall_id": SCRYFALL_ID, "quantity": 1},
            {"scryfall_id": SECOND_PRINTING_ID, "quantity": 1},
        ],
    })
    assert response.status_code == 200, response.text
    assert len(response.json()["cards"]) == 1
    assert response.json()["cards"][0]["quantity"] == 2

    # Membership is Oracle-level even when queried through the other printing.
    memberships = client.get(f"/api/cards/{SECOND_PRINTING_ID}/decks").json()
    assert [row["deck_name"] for row in memberships] == ["Oracle identity deck"]


def test_moxfield_preview_preserves_printing_hints_and_can_create_deck(
    client: TestClient,
) -> None:
    fixtures = [
        (
            "10000000-0000-4000-8000-000000000001",
            "20000000-0000-4000-8000-000000000001",
            "Big Apple, 3 a.m.", "tmc", "42", False,
        ),
        (
            "10000000-0000-4000-8000-000000000002",
            "20000000-0000-4000-8000-000000000002",
            "Bloodline Bidding", "msc", "155", True,
        ),
        (
            "10000000-0000-4000-8000-000000000003",
            "20000000-0000-4000-8000-000000000003",
            "Bubbling Muck", "plst", "UDS-54", False,
        ),
    ]
    with SessionLocal() as db:
        for printing_id, oracle_id, name, set_code, collector, _foil in fixtures:
            oracle = OracleCard(
                oracle_id=oracle_id,
                name=name,
                type_line="Sorcery",
                cmc=1,
                colors="B",
                color_identity="B",
                legalities_json='{"commander":"legal"}',
            )
            printing = CardPrinting(
                scryfall_id=printing_id,
                oracle=oracle,
                set_code=set_code,
                collector_number=collector,
                image_uri_normal=f"https://cards.test/{printing_id}.jpg",
            )
            db.add(printing)
            db.add(InventoryLine(
                scryfall_id=printing_id,
                quantity=2,
                foil=False,
                language="en",
            ))
        db.commit()

    text = (
        "1 Big Apple, 3 a.m. (TMC) 42\n"
        "1 Bloodline Bidding (MSC) 155 *F*\n"
        "1 Bubbling Muck (PLST) UDS-54"
    )
    preview = client.post("/api/decks/preview-text", json={"text": text})
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["row_errors"] == []
    assert payload["total_quantity"] == 3
    assert [card["name"] for card in payload["cards"]] == [
        "Big Apple, 3 a.m.", "Bloodline Bidding", "Bubbling Muck",
    ]
    assert payload["cards"][1]["foil"] is True
    assert payload["cards"][2]["collector_number"] == "UDS-54"
    assert payload["cards"][0]["colors"] == "B"
    assert all(card["owned_quantity"] == 2 for card in payload["cards"])

    cards = [
        {
            "scryfall_id": card["scryfall_id"],
            "quantity": card["quantity"],
            "is_commander": index == 0,
        }
        for index, card in enumerate(payload["cards"])
    ]
    created = client.post("/api/decks", json={
        "name": "Moxfield assembly",
        "format": "commander",
        "status": "building",
        "notes": "Created after previewing the assembly list.",
        "commander_scryfall_id": cards[0]["scryfall_id"],
        "cards": cards,
    })
    assert created.status_code == 200, created.text
    assert created.json()["name"] == "Moxfield assembly"
    assert sum(card["quantity"] for card in created.json()["cards"]) == 3
    assert sum(1 for card in created.json()["cards"] if card["is_commander"]) == 1


def test_assembly_preview_uses_stale_local_card_without_network(
    client: TestClient,
    monkeypatch,
) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        printing = db.get(CardPrinting, SCRYFALL_ID)
        printing.updated_at = datetime(2000, 1, 1)
        db.commit()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("A cached assembly card should not require Scryfall")

    monkeypatch.setattr("app.main.bulk_ensure_cards_cached_by_name", fail_if_called)
    response = client.post("/api/decks/preview-text", json={"text": "1 Test Ring"})
    assert response.status_code == 200, response.text
    assert response.json()["cards"][0]["scryfall_id"] == SCRYFALL_ID
    assert response.json()["row_errors"] == []


def test_request_limits_are_enforced(client: TestClient) -> None:
    original_limit = settings.max_upload_bytes
    settings.max_upload_bytes = 10
    try:
        response = client.post(
            "/api/import/manabox",
            files={"file": ("too-large.csv", b"x" * 11, "text/csv")},
        )
        assert response.status_code == 413
    finally:
        settings.max_upload_bytes = original_limit

    original_request_limit = settings.max_request_bytes
    settings.max_request_bytes = 10
    try:
        response = client.post("/api/inventory/clear", content=b"x" * 11)
        assert response.status_code == 413
    finally:
        settings.max_request_bytes = original_request_limit

    response = client.post("/api/enrichment/backfill-scryfall", json={"batch_size": 0})
    assert response.status_code == 422

    response = client.post(
        "/api/decks",
        json={
            "name": "Invalid deck",
            "cards": [{"scryfall_id": SCRYFALL_ID, "quantity": 0}],
        },
    )
    assert response.status_code == 422
