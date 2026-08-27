from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import (
    CardPrinting,
    Deck,
    DeckCard,
    DeckCardAllocation,
    InventoryLine,
    OracleCard,
)
from app.services.scryfall_client import ScryfallClient


ORACLE_ID = "10000000-0000-4000-8000-000000000001"
SOURCE_ID = "10000000-0000-4000-8000-000000000002"
TARGET_ID = "10000000-0000-4000-8000-000000000003"
OTHER_ID = "10000000-0000-4000-8000-000000000004"


def _payload(
    scryfall_id: str,
    *,
    set_code: str = "new",
    set_name: str = "New Set",
    collector_number: str = "42",
    foil: bool = True,
    nonfoil: bool = True,
    language: str = "en",
) -> dict:
    return {
        "id": scryfall_id,
        "oracle_id": ORACLE_ID,
        "name": "Test Ring",
        "type_line": "Artifact",
        "oracle_text": "{T}: Add {C}.",
        "mana_cost": "{1}",
        "cmc": 1,
        "colors": [],
        "color_identity": [],
        "legalities": {"commander": "legal"},
        "keywords": [],
        "set": set_code,
        "set_name": set_name,
        "collector_number": collector_number,
        "released_at": "2025-01-02",
        "lang": language,
        "foil": foil,
        "nonfoil": nonfoil,
        "rarity": "rare",
        "image_uris": {"normal": f"https://cards.test/{scryfall_id}.jpg"},
    }


def _seed_printings() -> None:
    with SessionLocal() as db:
        oracle = OracleCard(
            oracle_id=ORACLE_ID,
            name="Test Ring",
            type_line="Artifact",
            oracle_text="{T}: Add {C}.",
            mana_cost="{1}",
            cmc=1,
            colors="",
            color_identity="",
            legalities_json='{"commander": "legal"}',
        )
        db.add(oracle)
        db.add_all([
            CardPrinting(
                scryfall_id=SOURCE_ID,
                oracle=oracle,
                set_code="old",
                collector_number="1",
                language="en",
            ),
            CardPrinting(
                scryfall_id=TARGET_ID,
                oracle=oracle,
                set_code="new",
                collector_number="42",
                language="en",
            ),
        ])
        db.commit()


def _mock_target(monkeypatch: pytest.MonkeyPatch, payload: dict | None = None) -> None:
    target = payload or _payload(TARGET_ID)
    monkeypatch.setattr(
        "app.main.ScryfallClient.fetch_card_by_id",
        lambda _self, scryfall_id: target if scryfall_id == TARGET_ID else None,
    )


def test_scryfall_print_search_follows_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ScryfallClient()
    first_url = f"{client.base}/cards/search?q=first"
    second_url = f"{client.base}/cards/search?q=second&page=2"
    monkeypatch.setattr(
        client,
        "fetch_card_by_id",
        lambda _scryfall_id: {"prints_search_uri": first_url},
    )
    requested: list[str] = []

    def fake_request(_method: str, url: str, **_kwargs) -> httpx.Response:
        requested.append(url)
        request = httpx.Request("GET", url)
        if url == first_url:
            return httpx.Response(200, request=request, json={
                "data": [{"id": SOURCE_ID}],
                "has_more": True,
                "next_page": second_url,
            })
        return httpx.Response(200, request=request, json={
            "data": [{"id": TARGET_ID}],
            "has_more": False,
        })

    monkeypatch.setattr(client, "_request", fake_request)

    assert [row["id"] for row in client.fetch_prints_for_card(SOURCE_ID)] == [
        SOURCE_ID,
        TARGET_ID,
    ]
    assert requested == [first_url, second_url]


def test_print_options_preserve_duplicate_set_names_and_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_printings()
    face_image = "https://cards.test/transform-front.jpg"
    options = [
        _payload(SOURCE_ID, set_code="dup", set_name="Duplicate Set", collector_number="1"),
        {
            **_payload(TARGET_ID, set_code="dup", set_name="Duplicate Set", collector_number="2"),
            "image_uris": None,
            "card_faces": [{"image_uris": {"normal": face_image}}],
        },
        {**_payload(OTHER_ID), "oracle_id": "20000000-0000-4000-8000-000000000001"},
    ]
    monkeypatch.setattr(
        "app.main.ScryfallClient.fetch_prints_for_card",
        lambda _self, _scryfall_id: options,
    )

    response = client.get(f"/api/cards/{SOURCE_ID}/print-options")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 2
    assert [row["set_name"] for row in body] == ["Duplicate Set", "Duplicate Set"]
    assert [row["collector_number"] for row in body] == ["1", "2"]
    assert body[1] == {
        "scryfall_id": TARGET_ID,
        "name": "Test Ring",
        "set_name": "Duplicate Set",
        "set_code": "dup",
        "collector_number": "2",
        "released_at": "2025-01-02",
        "language": "en",
        "image_uri_normal": face_image,
        "foil": True,
        "nonfoil": True,
    }


def test_whole_printing_correction_merges_lines_and_exact_allocations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_printings()
    _mock_target(monkeypatch)
    with SessionLocal() as db:
        source_nonfoil = InventoryLine(
            scryfall_id=SOURCE_ID,
            quantity=2,
            foil=False,
            condition="near_mint",
            language="en",
        )
        source_foil = InventoryLine(
            scryfall_id=SOURCE_ID,
            quantity=1,
            foil=True,
            condition="near_mint",
            language="en",
        )
        target_nonfoil = InventoryLine(
            scryfall_id=TARGET_ID,
            quantity=3,
            foil=False,
            condition="near_mint",
            language="en",
        )
        deck = Deck(name="Allocation deck")
        db.add_all([source_nonfoil, source_foil, target_nonfoil, deck])
        db.flush()
        deck_card = DeckCard(
            deck_id=deck.id,
            scryfall_id=SOURCE_ID,
            oracle_id=ORACLE_ID,
            quantity=2,
            grabbed_quantity=2,
        )
        db.add(deck_card)
        db.flush()
        db.add_all([
            DeckCardAllocation(
                deck_card_id=deck_card.id,
                scryfall_id=SOURCE_ID,
                status="grabbed",
                quantity=1,
            ),
            DeckCardAllocation(
                deck_card_id=deck_card.id,
                scryfall_id=TARGET_ID,
                status="grabbed",
                quantity=1,
            ),
        ])
        db.commit()

    response = client.put(
        f"/api/inventory/printings/{SOURCE_ID}",
        json={"target_scryfall_id": TARGET_ID},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "changed_lines": 2,
        "moved_quantity": 3,
        "source_scryfall_id": SOURCE_ID,
        "target_scryfall_id": TARGET_ID,
    }
    with SessionLocal() as db:
        assert db.query(InventoryLine).filter(InventoryLine.scryfall_id == SOURCE_ID).count() == 0
        target_lines = db.query(InventoryLine).filter(
            InventoryLine.scryfall_id == TARGET_ID
        ).order_by(InventoryLine.foil).all()
        assert [(row.foil, row.quantity) for row in target_lines] == [(False, 5), (True, 1)]
        allocations = db.query(DeckCardAllocation).all()
        assert len(allocations) == 1
        assert (
            allocations[0].scryfall_id,
            allocations[0].status,
            allocations[0].quantity,
        ) == (TARGET_ID, "grabbed", 2)


def test_line_correction_preserves_metadata_and_other_source_lines(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_printings()
    _mock_target(monkeypatch)
    with SessionLocal() as db:
        moved = InventoryLine(
            scryfall_id=SOURCE_ID,
            quantity=2,
            foil=False,
            misprint=True,
            altered=True,
            condition="near_mint",
            language="en",
            set_code="old",
            collector_number="1",
            purchase_price=4.25,
            purchase_currency="USD",
            manabox_id="inventory-row-1",
        )
        retained = InventoryLine(
            scryfall_id=SOURCE_ID,
            quantity=1,
            foil=True,
            condition="near_mint",
            language="en",
        )
        db.add_all([moved, retained])
        db.commit()
        moved_id = moved.id
        retained_id = retained.id

    response = client.put(
        f"/api/inventory/lines/{moved_id}/printing",
        json={"target_scryfall_id": TARGET_ID},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        moved = db.get(InventoryLine, moved_id)
        assert moved is not None
        assert (
            moved.scryfall_id,
            moved.quantity,
            moved.foil,
            moved.misprint,
            moved.altered,
            moved.condition,
            moved.language,
            moved.set_code,
            moved.collector_number,
            moved.purchase_price,
            moved.purchase_currency,
            moved.manabox_id,
        ) == (
            TARGET_ID,
            2,
            False,
            True,
            True,
            "near_mint",
            "en",
            "new",
            "42",
            4.25,
            "USD",
            "inventory-row-1",
        )
        retained = db.get(InventoryLine, retained_id)
        assert retained is not None
        assert (retained.scryfall_id, retained.quantity, retained.foil) == (
            SOURCE_ID,
            1,
            True,
        )


def test_line_correction_can_split_and_move_one_copy(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_printings()
    _mock_target(monkeypatch)
    with SessionLocal() as db:
        source = InventoryLine(
            scryfall_id=SOURCE_ID,
            quantity=2,
            foil=False,
            condition="near_mint",
            language="en",
            set_code="old",
            collector_number="1",
            purchase_price=3.5,
            purchase_currency="USD",
        )
        db.add(source)
        db.commit()
        source_id = source.id

    response = client.put(
        f"/api/inventory/lines/{source_id}/printing",
        json={"target_scryfall_id": TARGET_ID, "quantity": 1},
    )

    assert response.status_code == 200, response.text
    assert response.json()["moved_quantity"] == 1
    with SessionLocal() as db:
        retained = db.get(InventoryLine, source_id)
        moved = db.query(InventoryLine).filter(
            InventoryLine.scryfall_id == TARGET_ID
        ).one()
        assert (retained.scryfall_id, retained.quantity) == (SOURCE_ID, 1)
        assert (
            moved.quantity,
            moved.foil,
            moved.condition,
            moved.language,
            moved.set_code,
            moved.collector_number,
            moved.purchase_price,
            moved.purchase_currency,
        ) == (1, False, "near_mint", "en", "new", "42", 3.5, "USD")


def test_line_correction_rejects_more_copies_than_the_line_contains(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_printings()
    _mock_target(monkeypatch)
    with SessionLocal() as db:
        source = InventoryLine(
            scryfall_id=SOURCE_ID, quantity=2, foil=False, language="en"
        )
        db.add(source)
        db.commit()
        source_id = source.id

    response = client.put(
        f"/api/inventory/lines/{source_id}/printing",
        json={"target_scryfall_id": TARGET_ID, "quantity": 3},
    )

    assert response.status_code == 422, response.text
    assert "has 2" in response.json()["detail"]


@pytest.mark.parametrize(
    ("line_foil", "line_language", "target_foil", "target_nonfoil", "target_language", "detail"),
    [
        (True, "en", False, True, "en", "not available in foil"),
        (False, "ja", True, True, "en", "inventory line is JA"),
    ],
)
def test_line_correction_rejects_incompatible_treatment_or_language(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    line_foil: bool,
    line_language: str,
    target_foil: bool,
    target_nonfoil: bool,
    target_language: str,
    detail: str,
) -> None:
    _seed_printings()
    _mock_target(monkeypatch, _payload(
        TARGET_ID,
        foil=target_foil,
        nonfoil=target_nonfoil,
        language=target_language,
    ))
    with SessionLocal() as db:
        line = InventoryLine(
            scryfall_id=SOURCE_ID,
            quantity=1,
            foil=line_foil,
            condition="near_mint",
            language=line_language,
        )
        db.add(line)
        db.commit()
        line_id = line.id

    response = client.put(
        f"/api/inventory/lines/{line_id}/printing",
        json={"target_scryfall_id": TARGET_ID},
    )

    assert response.status_code == 422, response.text
    assert detail in response.json()["detail"]
    with SessionLocal() as db:
        assert db.get(InventoryLine, line_id).scryfall_id == SOURCE_ID


def test_inventory_line_quantity_can_be_corrected(client: TestClient) -> None:
    _seed_printings()
    with SessionLocal() as db:
        line = InventoryLine(
            scryfall_id=SOURCE_ID,
            quantity=1,
            foil=False,
            condition="near_mint",
            language="en",
        )
        db.add(line)
        db.commit()
        line_id = line.id

    response = client.patch(
        f"/api/inventory/{line_id}",
        json={"quantity": 3},
    )

    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 3
    grouped = client.get("/api/inventory/grouped").json()
    assert grouped[0]["total_quantity"] == 3
    assert grouped[0]["printings"][0]["nonfoil_quantity"] == 3


def test_quantity_reduction_protects_exact_foil_assignments(
    client: TestClient,
) -> None:
    _seed_printings()
    with SessionLocal() as db:
        foil_line = InventoryLine(
            scryfall_id=SOURCE_ID, quantity=2, foil=True, language="en"
        )
        nonfoil_line = InventoryLine(
            scryfall_id=SOURCE_ID, quantity=5, foil=False, language="en"
        )
        deck = Deck(name="Foil allocation")
        db.add_all([foil_line, nonfoil_line, deck])
        db.flush()
        deck_card = DeckCard(
            deck_id=deck.id,
            scryfall_id=SOURCE_ID,
            oracle_id=ORACLE_ID,
            quantity=2,
            grabbed_quantity=2,
        )
        db.add(deck_card)
        db.flush()
        db.add(DeckCardAllocation(
            deck_card_id=deck_card.id,
            scryfall_id=SOURCE_ID,
            status="grabbed",
            quantity=2,
            foil=True,
        ))
        db.commit()
        foil_line_id = foil_line.id

    response = client.patch(
        f"/api/inventory/{foil_line_id}",
        json={"quantity": 1},
    )

    assert response.status_code == 409, response.text
    assert "foil quantity below 2" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.get(InventoryLine, foil_line_id).quantity == 2


def test_quantity_reduction_protects_any_printing_grabbed_copies(
    client: TestClient,
) -> None:
    _seed_printings()
    with SessionLocal() as db:
        line = InventoryLine(
            scryfall_id=SOURCE_ID, quantity=2, foil=False, language="en"
        )
        deck = Deck(name="Any-printing allocation")
        db.add_all([line, deck])
        db.flush()
        deck_card = DeckCard(
            deck_id=deck.id,
            scryfall_id=SOURCE_ID,
            oracle_id=ORACLE_ID,
            quantity=2,
            grabbed_quantity=2,
        )
        db.add(deck_card)
        db.flush()
        db.add(DeckCardAllocation(
            deck_card_id=deck_card.id,
            scryfall_id=None,
            status="grabbed",
            quantity=2,
        ))
        db.commit()
        line_id = line.id

    response = client.patch(
        f"/api/inventory/{line_id}",
        json={"quantity": 1},
    )

    assert response.status_code == 409, response.text
    assert "total ownership below 2" in response.json()["detail"]
