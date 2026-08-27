from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.models import CardPrinting, DeckInventoryAddition, InventoryLine, OracleCard


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


def test_grouped_inventory_combines_oracle_printings_and_foil_lines(
    client: TestClient,
) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        first = db.get(CardPrinting, SCRYFALL_ID)
        first.set_code = "one"
        first.collector_number = "1"
        first.image_uri_normal = "https://cards.test/one.jpg"
        db.add(CardPrinting(
            scryfall_id=SECOND_PRINTING_ID,
            oracle_id=first.oracle_id,
            set_code="two",
            collector_number="2",
            rarity="uncommon",
            language="en",
            image_uri_normal="https://cards.test/two.jpg",
        ))
        db.add_all([
            InventoryLine(
                scryfall_id=SCRYFALL_ID, quantity=2, foil=False,
                condition="near_mint", language="en",
            ),
            InventoryLine(
                scryfall_id=SCRYFALL_ID, quantity=1, foil=True,
                condition="near_mint", language="en",
            ),
            InventoryLine(
                scryfall_id=SECOND_PRINTING_ID, quantity=3, foil=False,
                condition="good", language="en",
            ),
        ])
        db.commit()

    response = client.get("/api/inventory/grouped?q=ring")
    assert response.status_code == 200, response.text
    groups = response.json()
    assert len(groups) == 1
    group = groups[0]
    assert group["oracle_id"] == "00000000-0000-4000-8000-000000000002"
    assert group["total_quantity"] == 6
    assert group["printing_count"] == 2
    assert group["inventory_line_count"] == 3
    assert group["card"]["name"] == "Test Ring"

    first_printing, second_printing = group["printings"]
    assert first_printing["scryfall_id"] == SCRYFALL_ID
    assert first_printing["total_quantity"] == 3
    assert first_printing["foil_quantity"] == 1
    assert first_printing["nonfoil_quantity"] == 2
    assert len(first_printing["lines"]) == 2
    assert second_printing["scryfall_id"] == SECOND_PRINTING_ID
    assert second_printing["total_quantity"] == 3
    assert second_printing["foil_quantity"] == 0


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


def test_selecting_commander_enforces_eligibility_legality_and_one_commander(
    client: TestClient,
) -> None:
    fixtures = [
        (
            "40000000-0000-4000-8000-000000000001",
            "50000000-0000-4000-8000-000000000001",
            "First Captain",
            "Legendary Creature — Human",
            "legal",
        ),
        (
            "40000000-0000-4000-8000-000000000002",
            "50000000-0000-4000-8000-000000000002",
            "Second Captain",
            "Legendary Creature — Elf",
            "legal",
        ),
        (
            "40000000-0000-4000-8000-000000000003",
            "50000000-0000-4000-8000-000000000003",
            "Ordinary Rock",
            "Artifact",
            "legal",
        ),
        (
            "40000000-0000-4000-8000-000000000004",
            "50000000-0000-4000-8000-000000000004",
            "Banned Captain",
            "Legendary Creature — Human",
            "banned",
        ),
    ]
    with SessionLocal() as db:
        for scryfall_id, oracle_id, name, type_line, commander_legality in fixtures:
            oracle = OracleCard(
                oracle_id=oracle_id,
                name=name,
                type_line=type_line,
                legalities_json=f'{{"commander":"{commander_legality}"}}',
            )
            db.add(CardPrinting(scryfall_id=scryfall_id, oracle=oracle))
        db.commit()

    created = client.post("/api/decks", json={
        "name": "Commander selection",
        "format": "commander",
        "cards": [
            {"scryfall_id": scryfall_id, "quantity": 1}
            for scryfall_id, *_rest in fixtures
        ],
    })
    assert created.status_code == 200, created.text
    deck = created.json()
    entries = {entry["card"]["name"]: entry for entry in deck["cards"]}

    ineligible = client.put(
        f"/api/decks/{deck['id']}/cards/{entries['Ordinary Rock']['id']}/commander"
    )
    assert ineligible.status_code == 422
    assert "cannot be the commander" in ineligible.json()["detail"]

    banned = client.put(
        f"/api/decks/{deck['id']}/cards/{entries['Banned Captain']['id']}/commander"
    )
    assert banned.status_code == 422
    assert "legality is banned" in banned.json()["detail"]

    selected = client.put(
        f"/api/decks/{deck['id']}/cards/{entries['First Captain']['id']}/commander"
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["commander_scryfall_id"] == fixtures[0][0]
    assert [
        entry["card"]["name"]
        for entry in selected.json()["cards"]
        if entry["is_commander"]
    ] == ["First Captain"]

    switched = client.patch(
        f"/api/decks/{deck['id']}",
        json={"commander_scryfall_id": fixtures[1][0]},
    )
    assert switched.status_code == 200, switched.text
    assert [
        entry["card"]["name"]
        for entry in switched.json()["cards"]
        if entry["is_commander"]
    ] == ["Second Captain"]

    second_entry = next(
        entry for entry in switched.json()["cards"]
        if entry["card"]["name"] == "Second Captain"
    )
    removed = client.delete(
        f"/api/decks/{deck['id']}/cards/{second_entry['id']}"
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["commander_scryfall_id"] is None
    assert not any(entry["is_commander"] for entry in removed.json()["cards"])


def test_create_and_add_card_routes_cannot_bypass_commander_validation(
    client: TestClient,
) -> None:
    legal_id = "41000000-0000-4000-8000-000000000001"
    other_legal_id = "41000000-0000-4000-8000-000000000002"
    artifact_id = "41000000-0000-4000-8000-000000000003"
    fixtures = [
        (legal_id, "51000000-0000-4000-8000-000000000001", "Legal Captain", "Legendary Creature — Human"),
        (other_legal_id, "51000000-0000-4000-8000-000000000002", "Other Captain", "Legendary Creature — Elf"),
        (artifact_id, "51000000-0000-4000-8000-000000000003", "Commander-Shaped Rock", "Artifact"),
    ]
    with SessionLocal() as db:
        for scryfall_id, oracle_id, name, type_line in fixtures:
            db.add(CardPrinting(
                scryfall_id=scryfall_id,
                oracle=OracleCard(
                    oracle_id=oracle_id,
                    name=name,
                    type_line=type_line,
                    legalities_json='{"commander":"legal"}',
                ),
            ))
        db.commit()

    invalid_create = client.post("/api/decks", json={
        "name": "Invalid commander create",
        "cards": [{"scryfall_id": artifact_id, "is_commander": True}],
    })
    assert invalid_create.status_code == 422
    assert "cannot be the commander" in invalid_create.json()["detail"]

    multiple_create = client.post("/api/decks", json={
        "name": "Multiple commanders",
        "cards": [
            {"scryfall_id": legal_id, "is_commander": True},
            {"scryfall_id": other_legal_id, "is_commander": True},
        ],
    })
    assert multiple_create.status_code == 422
    assert "only one" in multiple_create.json()["detail"]

    deck = client.post("/api/decks", json={
        "name": "Add route validation",
        "cards": [{"scryfall_id": legal_id}],
    }).json()
    invalid_add = client.post(f"/api/decks/{deck['id']}/cards", json=[
        {"scryfall_id": artifact_id, "is_commander": True},
    ])
    assert invalid_add.status_code == 422
    assert "cannot be the commander" in invalid_add.json()["detail"]

    selected = client.post(f"/api/decks/{deck['id']}/cards", json=[
        {"scryfall_id": other_legal_id, "is_commander": True},
    ])
    assert selected.status_code == 200, selected.text
    assert selected.json()["commander_scryfall_id"] == other_legal_id
    assert sum(card["is_commander"] for card in selected.json()["cards"]) == 1


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
        for index, (printing_id, oracle_id, name, set_code, collector, _foil) in enumerate(fixtures):
            oracle = OracleCard(
                oracle_id=oracle_id,
                name=name,
                type_line="Legendary Creature — Avatar" if index == 0 else "Sorcery",
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

    listed = client.get("/api/decks")
    assert listed.status_code == 200, listed.text
    listed_deck = next(deck for deck in listed.json() if deck["id"] == created.json()["id"])
    assert listed_deck["commander_name"] == "Big Apple, 3 a.m."

    renamed = client.patch(
        f"/api/decks/{created.json()['id']}",
        json={"name": "Renamed Moxfield assembly"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Renamed Moxfield assembly"


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


def test_deck_assembly_tracks_physical_copies_proxies_and_demand(
    client: TestClient,
) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        db.commit()

    created = client.post("/api/decks", json={
        "name": "Allocation test",
        "cards": [{"scryfall_id": SCRYFALL_ID, "quantity": 2}],
    })
    assert created.status_code == 200, created.text
    deck = created.json()
    entry = deck["cards"][0]
    assert entry["grabbed_quantity"] == 0
    assert entry["proxy_quantity"] == 0

    grabbed = client.put(
        f"/api/decks/{deck['id']}/cards/{entry['id']}/assembly?compact=true",
        json={"grabbed_quantity": 1, "proxy_quantity": 0},
    )
    assert grabbed.status_code == 200, grabbed.text
    assert grabbed.json()["id"] == entry["id"]
    assert grabbed.json()["grabbed_quantity"] == 1
    assert client.get("/api/inventory").json()[0]["quantity"] == 1

    locations = client.get(f"/api/cards/{SCRYFALL_ID}/locations").json()
    assert locations == {
        "scryfall_id": SCRYFALL_ID,
        "oracle_id": "00000000-0000-4000-8000-000000000002",
        "owned_total": 1,
        "grabbed_total": 1,
        "bulk_total": 0,
        "pending_total": 1,
        "proxy_total": 0,
        "freely_available": 0,
        "demand_shortfall": 1,
        "decks": [{
            "deck_id": deck["id"],
            "deck_name": "Allocation test",
            "is_commander": False,
            "quantity": 2,
            "grabbed_quantity": 1,
            "proxy_quantity": 0,
            "pending_quantity": 1,
        }],
    }

    second_copy = client.put(
        f"/api/decks/{deck['id']}/cards/{entry['id']}/assembly",
        json={"grabbed_quantity": 2, "proxy_quantity": 0},
    )
    assert second_copy.status_code == 200, second_copy.text
    assert client.get("/api/inventory").json()[0]["quantity"] == 2

    proxied = client.put(
        f"/api/decks/{deck['id']}/cards/{entry['id']}/assembly",
        json={"grabbed_quantity": 1, "proxy_quantity": 1},
    )
    assert proxied.status_code == 200, proxied.text
    locations = client.get(f"/api/cards/{SCRYFALL_ID}/locations").json()
    assert locations["owned_total"] == 2
    assert locations["grabbed_total"] == 1
    assert locations["bulk_total"] == 1
    assert locations["freely_available"] == 1
    assert locations["proxy_total"] == 1
    assert locations["pending_total"] == 0


def test_deck_card_exact_printing_allocations_are_replaceable(
    client: TestClient,
) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        oracle = db.get(OracleCard, "00000000-0000-4000-8000-000000000002")
        db.add(CardPrinting(
            scryfall_id=SECOND_PRINTING_ID,
            oracle=oracle,
            rarity="uncommon",
            set_code="tst",
            collector_number="2",
        ))
        db.add(InventoryLine(
            scryfall_id=SCRYFALL_ID,
            quantity=1,
            foil=False,
            language="en",
        ))
        db.commit()

    created = client.post("/api/decks", json={
        "name": "Exact printing deck",
        "cards": [{"scryfall_id": SCRYFALL_ID, "quantity": 3}],
    })
    assert created.status_code == 200, created.text
    deck = created.json()
    entry = deck["cards"][0]
    assert entry["allocations"] == [{
        "id": entry["allocations"][0]["id"],
        "status": "pending",
        "quantity": 3,
        "scryfall_id": None,
        "foil": None,
        "printing": None,
    }]

    replaced = client.put(
        f"/api/decks/{deck['id']}/cards/{entry['id']}/allocations",
        json={"allocations": [
            {"status": "grabbed", "quantity": 1, "scryfall_id": SCRYFALL_ID, "foil": False},
            {"status": "pending", "quantity": 1, "scryfall_id": None},
            {"status": "proxy", "quantity": 1, "scryfall_id": SECOND_PRINTING_ID},
        ]},
    )
    assert replaced.status_code == 200, replaced.text
    updated_entry = replaced.json()["cards"][0]
    assert updated_entry["grabbed_quantity"] == 1
    assert updated_entry["proxy_quantity"] == 1
    assert {
        (row["status"], row["scryfall_id"], row["quantity"])
        for row in updated_entry["allocations"]
    } == {
        ("grabbed", SCRYFALL_ID, 1),
        ("pending", None, 1),
        ("proxy", SECOND_PRINTING_ID, 1),
    }
    exact_rows = {
        row["scryfall_id"]: row for row in updated_entry["allocations"]
        if row["scryfall_id"]
    }
    assert exact_rows[SCRYFALL_ID]["printing"]["name"] == "Test Ring"
    assert exact_rows[SCRYFALL_ID]["foil"] is False
    assert exact_rows[SECOND_PRINTING_ID]["printing"]["scryfall_id"] == SECOND_PRINTING_ID

    locations = client.get(
        f"/api/cards/{SCRYFALL_ID}/locations?include_printings=true"
    )
    assert locations.status_code == 200, locations.text
    location_body = locations.json()
    assert location_body["any_printing"] == {
        "grabbed": 0,
        "pending": 1,
        "proxy": 0,
    }
    by_printing = {
        row["scryfall_id"]: row for row in location_body["printings"]
    }
    assert by_printing[SCRYFALL_ID]["grabbed_quantity"] == 1
    assert by_printing[SECOND_PRINTING_ID]["proxy_quantity"] == 1


def test_inventory_cannot_remove_assigned_copy_and_clear_releases_assignments(
    client: TestClient,
) -> None:
    _add_cached_card()
    created = client.post("/api/decks", json={
        "name": "Physical deck",
        "cards": [{"scryfall_id": SCRYFALL_ID}],
    }).json()
    entry = created["cards"][0]
    response = client.put(
        f"/api/decks/{created['id']}/cards/{entry['id']}/assembly",
        json={"grabbed_quantity": 1, "proxy_quantity": 0},
    )
    assert response.status_code == 200, response.text
    inventory_id = client.get("/api/inventory").json()[0]["id"]

    blocked = client.delete(f"/api/inventory/{inventory_id}")
    assert blocked.status_code == 409

    cleared = client.post("/api/inventory/clear")
    assert cleared.status_code == 200
    deck = client.get(f"/api/decks/{created['id']}").json()
    assert deck["cards"][0]["grabbed_quantity"] == 0
    assert deck["cards"][0]["proxy_quantity"] == 0
    assert client.get("/api/inventory").json() == []


def test_deleting_deck_returns_grabbed_copy_to_bulk(client: TestClient) -> None:
    _add_cached_card()
    created = client.post("/api/decks", json={
        "name": "Temporary deck",
        "cards": [{"scryfall_id": SCRYFALL_ID}],
    }).json()
    entry = created["cards"][0]
    assert client.put(
        f"/api/decks/{created['id']}/cards/{entry['id']}/assembly",
        json={"grabbed_quantity": 1, "proxy_quantity": 0},
    ).status_code == 200

    assert client.delete(f"/api/decks/{created['id']}").status_code == 200
    locations = client.get(f"/api/cards/{SCRYFALL_ID}/locations").json()
    assert locations["owned_total"] == 1
    assert locations["grabbed_total"] == 0
    assert locations["bulk_total"] == 1
    assert locations["decks"] == []


def test_deck_import_creates_demand_without_adding_inventory(client: TestClient) -> None:
    _add_cached_card()
    response = client.post(
        "/api/decks/import-csv",
        data={"deck_name": "Imported demand", "format": "commander", "status": "building"},
        files={"file": ("deck.csv", f"Scryfall ID,Quantity\n{SCRYFALL_ID},2\n", "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["deck"]["cards"][0]["grabbed_quantity"] == 0
    assert client.get("/api/inventory").json() == []


def test_deck_draft_save_atomically_replaces_metadata_copies_and_prints(
    client: TestClient,
) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        oracle = db.get(OracleCard, "00000000-0000-4000-8000-000000000002")
        db.add(CardPrinting(
            scryfall_id=SECOND_PRINTING_ID,
            oracle=oracle,
            rarity="uncommon",
            set_code="two",
            collector_number="2",
        ))
        db.commit()

    created = client.post("/api/decks", json={
        "name": "Draft before save",
        "format": "commander",
        "cards": [{"scryfall_id": SCRYFALL_ID}],
    }).json()

    draft = {
        "name": "Draft after save",
        "format": "commander",
        "status": "complete",
        "notes": "Saved in one transaction",
        "cards": [
            {
                "card_scryfall_id": SCRYFALL_ID,
                "printing_scryfall_id": SCRYFALL_ID,
                "status": "grabbed",
                "foil": False,
                "add_to_collection": True,
                "collection_addition_id": "00000000-0000-4000-8000-000000000010",
            },
            {
                "card_scryfall_id": SCRYFALL_ID,
                "printing_scryfall_id": SECOND_PRINTING_ID,
                "status": "proxy",
            },
        ],
    }
    saved = client.put(f"/api/decks/{created['id']}/draft", json=draft)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["name"] == "Draft after save"
    assert body["status"] == "complete"
    assert body["notes"] == "Saved in one transaction"
    assert len(body["cards"]) == 1
    assert body["cards"][0]["quantity"] == 2
    assert body["cards"][0]["grabbed_quantity"] == 1
    assert body["cards"][0]["proxy_quantity"] == 1
    assert {
        (row["status"], row["scryfall_id"], row["foil"])
        for row in body["cards"][0]["allocations"]
    } == {
        ("grabbed", SCRYFALL_ID, False),
        ("proxy", SECOND_PRINTING_ID, None),
    }
    assert sum(row["quantity"] for row in client.get("/api/inventory").json()) == 1

    replayed = client.put(f"/api/decks/{created['id']}/draft", json=draft)
    assert replayed.status_code == 200, replayed.text
    assert sum(row["quantity"] for row in client.get("/api/inventory").json()) == 1
    with SessionLocal() as db:
        assert db.query(DeckInventoryAddition).count() == 1


def test_invalid_deck_draft_rolls_back_all_card_and_metadata_changes(
    client: TestClient,
) -> None:
    _add_cached_card()
    created = client.post("/api/decks", json={
        "name": "Keep this deck",
        "format": "commander",
        "cards": [{"scryfall_id": SCRYFALL_ID}],
    }).json()

    invalid = client.put(f"/api/decks/{created['id']}/draft", json={
        "name": "Must roll back",
        "format": "commander",
        "status": "complete",
        "cards": [{
            "card_scryfall_id": SCRYFALL_ID,
            "printing_scryfall_id": SCRYFALL_ID,
            "status": "grabbed",
            "foil": False,
            "is_commander": True,
            "add_to_collection": True,
            "collection_addition_id": "00000000-0000-4000-8000-000000000011",
        }],
    })
    assert invalid.status_code == 422
    assert "cannot be the commander" in invalid.json()["detail"]

    unchanged = client.get(f"/api/decks/{created['id']}").json()
    assert unchanged["name"] == "Keep this deck"
    assert unchanged["status"] == "building"
    assert unchanged["commander_scryfall_id"] is None
    assert unchanged["cards"][0]["quantity"] == 1
    assert unchanged["cards"][0]["grabbed_quantity"] == 0
    assert unchanged["cards"][0]["is_commander"] is False
    assert client.get("/api/inventory").json() == []
    with SessionLocal() as db:
        assert db.query(DeckInventoryAddition).count() == 0


def test_deck_draft_save_preserves_sideboard_cards(client: TestClient) -> None:
    _add_cached_card()
    created = client.post("/api/decks", json={
        "name": "Sideboard draft",
        "format": "standard",
        "cards": [{"scryfall_id": SCRYFALL_ID, "is_sideboard": True}],
    }).json()

    saved = client.put(f"/api/decks/{created['id']}/draft", json={
        "name": "Sideboard draft",
        "format": "standard",
        "status": "building",
        "cards": [{
            "card_scryfall_id": SCRYFALL_ID,
            "printing_scryfall_id": SCRYFALL_ID,
            "status": "pending",
            "is_sideboard": True,
        }],
    })

    assert saved.status_code == 200, saved.text
    assert len(saved.json()["cards"]) == 1
    assert saved.json()["cards"][0]["is_sideboard"] is True


def test_add_inventory_card_merges_matching_lines_and_separates_foil(
    client: TestClient,
) -> None:
    _add_cached_card()

    first = client.post("/api/inventory", json={
        "scryfall_id": SCRYFALL_ID,
        "quantity": 2,
        "foil": False,
    })
    assert first.status_code == 200, first.text
    assert first.json()["quantity"] == 2

    merged = client.post("/api/inventory", json={
        "scryfall_id": SCRYFALL_ID,
        "quantity": 3,
        "foil": False,
    })
    assert merged.status_code == 200, merged.text
    assert merged.json()["id"] == first.json()["id"]
    assert merged.json()["quantity"] == 5

    foil = client.post("/api/inventory", json={
        "scryfall_id": SCRYFALL_ID,
        "quantity": 1,
        "foil": True,
    })
    assert foil.status_code == 200, foil.text
    assert foil.json()["id"] != first.json()["id"]

    grouped = client.get("/api/inventory/grouped").json()[0]
    assert grouped["total_quantity"] == 6
    assert grouped["printings"][0]["nonfoil_quantity"] == 5
    assert grouped["printings"][0]["foil_quantity"] == 1


def test_deck_csv_preview_and_card_resolution_do_not_mutate_a_deck(
    client: TestClient,
) -> None:
    _add_cached_card()
    created = client.post("/api/decks", json={
        "name": "Unchanged deck",
        "cards": [{"scryfall_id": SCRYFALL_ID}],
    }).json()

    preview = client.post(
        "/api/decks/preview-csv",
        files={"file": (
            "deck.csv",
            f"Scryfall ID,Quantity,Foil\n{SCRYFALL_ID},2,false\n",
            "text/csv",
        )},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["cards"][0]["quantity"] == 2

    resolved = client.get("/api/cards/resolve", params={"q": SCRYFALL_ID})
    assert resolved.status_code == 200, resolved.text
    match = resolved.json()["matches"][0]
    assert match["scryfall_id"] == SCRYFALL_ID
    assert match["name"] == "Test Ring"
    assert match["type_line"] == "Artifact"

    unchanged = client.get(f"/api/decks/{created['id']}").json()
    assert unchanged["name"] == "Unchanged deck"
    assert unchanged["cards"][0]["quantity"] == 1


def test_proxy_to_grabbed_does_not_consume_another_decks_earmarked_copy(
    client: TestClient,
) -> None:
    _add_cached_card()
    with SessionLocal() as db:
        db.add(InventoryLine(
            scryfall_id=SCRYFALL_ID, quantity=1, foil=False, language="en"
        ))
        db.commit()
    pending_deck = client.post("/api/decks", json={
        "name": "Pending deck",
        "cards": [{"scryfall_id": SCRYFALL_ID}],
    }).json()
    proxy_deck = client.post("/api/decks", json={
        "name": "Proxy deck",
        "cards": [{"scryfall_id": SCRYFALL_ID}],
    }).json()
    proxy_entry = proxy_deck["cards"][0]
    assert client.put(
        f"/api/decks/{proxy_deck['id']}/cards/{proxy_entry['id']}/assembly",
        json={"grabbed_quantity": 0, "proxy_quantity": 1},
    ).status_code == 200

    grabbed = client.put(
        f"/api/decks/{proxy_deck['id']}/cards/{proxy_entry['id']}/assembly",
        json={"grabbed_quantity": 1, "proxy_quantity": 0},
    )
    assert grabbed.status_code == 200, grabbed.text
    locations = client.get(f"/api/cards/{SCRYFALL_ID}/locations").json()
    assert locations["owned_total"] == 2
    assert locations["grabbed_total"] == 1
    assert locations["pending_total"] == 1
    assert locations["freely_available"] == 0
    assert locations["decks"][0]["deck_id"] == pending_deck["id"]


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
