from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import CardPrinting, Deck, DeckCard, InventoryLine, OracleCard


ORACLE_A = "80000000-0000-4000-8000-000000000001"
PRINTING_A = "80000000-0000-4000-8000-000000000002"
ORACLE_B = "80000000-0000-4000-8000-000000000003"
PRINTING_B = "80000000-0000-4000-8000-000000000004"


def test_proxy_scan_groups_replaceable_cards_and_does_not_double_count(
    client: TestClient,
) -> None:
    with SessionLocal() as db:
        card_a = OracleCard(oracle_id=ORACLE_A, name="Available A")
        card_b = OracleCard(oracle_id=ORACLE_B, name="Available B")
        db.add_all([card_a, card_b])
        db.add_all([
            CardPrinting(scryfall_id=PRINTING_A, oracle=card_a),
            CardPrinting(scryfall_id=PRINTING_B, oracle=card_b),
        ])
        db.flush()
        db.add_all([
            InventoryLine(scryfall_id=PRINTING_A, quantity=2, foil=False, language="en"),
            InventoryLine(scryfall_id=PRINTING_B, quantity=1, foil=False, language="en"),
        ])
        first = Deck(name="Deck One", format="commander", status="building")
        second = Deck(name="Deck Two", format="commander", status="building")
        db.add_all([first, second])
        db.flush()
        first_card = DeckCard(
            deck_id=first.id,
            scryfall_id=PRINTING_A,
            oracle_id=ORACLE_A,
            quantity=3,
            grabbed_quantity=1,
            proxy_quantity=2,
        )
        second_card_a = DeckCard(
            deck_id=second.id,
            scryfall_id=PRINTING_A,
            oracle_id=ORACLE_A,
            quantity=1,
            proxy_quantity=1,
        )
        second_card_b = DeckCard(
            deck_id=second.id,
            scryfall_id=PRINTING_B,
            oracle_id=ORACLE_B,
            quantity=1,
            proxy_quantity=1,
        )
        db.add_all([first_card, second_card_a, second_card_b])
        db.flush()
        first_id = first.id
        second_id = second.id
        first_card_id = first_card.id
        second_card_b_id = second_card_b.id
        db.commit()

    response = client.get("/api/decks/proxy-replacements")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "scanned_proxy_cards": 4,
        "replaceable_proxy_cards": 2,
        "decks": [
            {
                "deck_id": first_id,
                "deck_name": "Deck One",
                "cards": [{
                    "deck_card_id": first_card_id,
                    "oracle_id": ORACLE_A,
                    "name": "Available A",
                    "quantity": 1,
                }],
            },
            {
                "deck_id": second_id,
                "deck_name": "Deck Two",
                "cards": [{
                    "deck_card_id": second_card_b_id,
                    "oracle_id": ORACLE_B,
                    "name": "Available B",
                    "quantity": 1,
                }],
            },
        ],
    }


def test_proxy_scan_returns_empty_summary_without_proxies(client: TestClient) -> None:
    response = client.get("/api/decks/proxy-replacements")
    assert response.status_code == 200
    assert response.json() == {
        "scanned_proxy_cards": 0,
        "replaceable_proxy_cards": 0,
        "decks": [],
    }
