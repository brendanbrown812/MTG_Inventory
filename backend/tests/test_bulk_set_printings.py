from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import CardPrinting, OracleCard


ORACLE_ONE = "90000000-0000-4000-8000-000000000001"
SOURCE_ONE = "90000000-0000-4000-8000-000000000002"
TARGET_ONE = "90000000-0000-4000-8000-000000000003"
ORACLE_MISSING = "90000000-0000-4000-8000-000000000004"


def _payload() -> dict:
    return {
        "id": TARGET_ONE,
        "oracle_id": ORACLE_ONE,
        "name": "Set Card",
        "type_line": "Artifact",
        "oracle_text": "Test",
        "mana_cost": "{1}",
        "cmc": 1,
        "colors": [],
        "color_identity": [],
        "legalities": {},
        "keywords": [],
        "set": "scd",
        "set_name": "Sample Commander Deck",
        "collector_number": "12",
        "lang": "en",
        "foil": True,
        "nonfoil": True,
        "image_uris": {"normal": "https://cards.test/scd.jpg"},
    }


def test_bulk_set_printings_returns_matches_and_missing_cards(
    client: TestClient,
    monkeypatch,
) -> None:
    with SessionLocal() as db:
        oracle = OracleCard(oracle_id=ORACLE_ONE, name="Set Card")
        db.add(oracle)
        db.add(CardPrinting(scryfall_id=SOURCE_ONE, oracle=oracle, set_code="old"))
        db.commit()

    monkeypatch.setattr(
        "app.main.ScryfallClient.fetch_cards_in_set",
        lambda _self, set_code: [_payload()] if set_code == "scd" else [],
    )
    response = client.post("/api/printings/by-set", json={
        "set_code": "SCD",
        "oracle_ids": [ORACLE_ONE, ORACLE_MISSING, ORACLE_ONE],
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["set_code"] == "SCD"
    assert payload["missing_oracle_ids"] == [ORACLE_MISSING]
    assert payload["matches"] == [{
        "oracle_id": ORACLE_ONE,
        "printing": {
            "scryfall_id": TARGET_ONE,
            "oracle_id": ORACLE_ONE,
            "name": "Set Card",
            "type_line": "Artifact",
            "mana_cost": "{1}",
            "cmc": 1.0,
            "colors": "",
            "color_identity": "",
            "rarity": None,
            "set_code": "scd",
            "collector_number": "12",
            "image_uri_normal": "https://cards.test/scd.jpg",
        },
        "foil": True,
        "nonfoil": True,
    }]
    with SessionLocal() as db:
        assert db.get(CardPrinting, TARGET_ONE).set_code == "scd"


def test_bulk_set_printings_validates_set_code(client: TestClient) -> None:
    response = client.post("/api/printings/by-set", json={
        "set_code": "not a set",
        "oracle_ids": [ORACLE_ONE],
    })
    assert response.status_code == 422
