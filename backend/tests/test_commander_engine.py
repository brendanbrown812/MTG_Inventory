from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import CardPrinting, Deck, DeckCard, InventoryLine, OracleCard
from app.services.commander_engine import analyze_commander_deck, commander_eligibility


def _id() -> str:
    return str(uuid.uuid4())


def _card(
    db: Session,
    name: str,
    *,
    type_line: str = "Artifact",
    oracle_text: str = "",
    mana_cost: str = "{1}",
    cmc: float = 1,
    color_identity: str = "",
    legal: str = "legal",
    produced_mana: list[str] | None = None,
    power: str | None = None,
    toughness: str | None = None,
    oracle: OracleCard | None = None,
) -> CardPrinting:
    if oracle is None:
        oracle = OracleCard(
            oracle_id=_id(),
            name=name,
            type_line=type_line,
            oracle_text=oracle_text,
            mana_cost=mana_cost,
            cmc=cmc,
            colors=color_identity,
            color_identity=color_identity,
            legalities_json=json.dumps({"commander": legal}),
            keywords="[]",
        )
        db.add(oracle)
    payload: dict[str, object] = {}
    if produced_mana is not None:
        payload["produced_mana"] = produced_mana
    if power is not None:
        payload["power"] = power
    if toughness is not None:
        payload["toughness"] = toughness
    printing = CardPrinting(
        scryfall_id=_id(),
        oracle=oracle,
        scryfall_json=json.dumps(payload),
    )
    db.add(printing)
    db.flush()
    return printing


def _deck(db: Session, commander: CardPrinting, cards: list[tuple[CardPrinting, int]]) -> Deck:
    deck = Deck(
        name="Engine Test",
        format="commander",
        status="building",
        commander_scryfall_id=commander.scryfall_id,
        commander_oracle_id=commander.oracle_id,
    )
    db.add(deck)
    db.flush()
    for printing, quantity in cards:
        db.add(DeckCard(
            deck_id=deck.id,
            scryfall_id=printing.scryfall_id,
            oracle_id=printing.oracle_id,
            quantity=quantity,
            is_commander=printing.oracle_id == commander.oracle_id,
            is_sideboard=False,
        ))
    db.flush()
    return deck


def _hold(db: Session, printing: CardPrinting, quantity: int) -> None:
    db.add(InventoryLine(
        scryfall_id=printing.scryfall_id,
        quantity=quantity,
        foil=False,
        language="en",
    ))
    db.flush()


def _codes(report: dict, section: str) -> set[str]:
    return {finding["code"] for finding in report[section]["findings"]}


def test_legal_100_card_deck_and_singleton_exceptions() -> None:
    with SessionLocal() as db:
        commander = _card(
            db, "Test Commander", type_line="Legendary Creature — Elf",
            mana_cost="{2}{G}", cmc=3, color_identity="G",
        )
        forest = _card(
            db, "Forest", type_line="Basic Land — Forest", mana_cost="", cmc=0,
            color_identity="G", produced_mana=["G"],
        )
        unlimited = _card(
            db, "Persistent Test", type_line="Creature — Test", color_identity="G",
            oracle_text="A deck can have any number of cards named Persistent Test.",
        )
        deck = _deck(db, commander, [(commander, 1), (forest, 40), (unlimited, 59)])
        _hold(db, commander, 1)
        _hold(db, forest, 40)
        _hold(db, unlimited, 59)

        report = analyze_commander_deck(db, deck)

    assert report["deck_size"] == {"actual": 100, "required": 100, "delta": 0}
    assert report["legal"] is True
    assert report["available"] is True
    assert report["health"]["lands"]["count"] == 40
    assert "singleton_violation" not in _codes(report, "legality")


def test_color_identity_and_commander_format_legality() -> None:
    with SessionLocal() as db:
        commander = _card(
            db, "Green Leader", type_line="Legendary Creature — Elf", color_identity="G",
        )
        off_color = _card(
            db, "Hybrid Intruder", mana_cost="{G/U}", color_identity="G,U",
        )
        banned = _card(db, "Banned Test", color_identity="G", legal="banned")
        deck = _deck(db, commander, [(commander, 1), (off_color, 1), (banned, 1)])
        report = analyze_commander_deck(db, deck)

    codes = _codes(report, "legality")
    assert report["legal"] is False
    assert "color_identity" in codes
    assert "format_illegal_card" in codes
    color_finding = next(f for f in report["legality"]["findings"] if f["code"] == "color_identity")
    assert color_finding["details"]["off_colors"] == ["U"]


def test_singleton_limits_and_invalid_quantities() -> None:
    with SessionLocal() as db:
        commander = _card(db, "Leader", type_line="Legendary Creature — Human")
        duplicate = _card(db, "Ordinary Spell")
        seven = _card(
            db, "Seven Testers", type_line="Creature — Dwarf",
            oracle_text="A deck can have up to seven cards named Seven Testers.",
        )
        zero = _card(db, "Zero Test")
        deck = _deck(
            db, commander,
            [(commander, 1), (duplicate, 2), (seven, 8), (zero, 0)],
        )
        report = analyze_commander_deck(db, deck)

    singleton = [
        finding for finding in report["legality"]["findings"]
        if finding["code"] == "singleton_violation"
    ]
    assert {(f["details"]["card_name"], f["details"]["limit"]) for f in singleton} == {
        ("Ordinary Spell", 1), ("Seven Testers", 7),
    }
    assert "invalid_quantity" in _codes(report, "legality")


def test_commander_eligibility_variants() -> None:
    with SessionLocal() as db:
        legendary = _card(db, "Legend", type_line="Legendary Creature — Human")
        planeswalker = _card(
            db, "Special Walker", type_line="Legendary Planeswalker — Test",
            oracle_text="Special Walker can be your commander.",
        )
        vehicle = _card(
            db, "Flagship", type_line="Legendary Artifact — Vehicle", power="5", toughness="5",
        )
        powerless_vehicle = _card(
            db, "Old Cart", type_line="Legendary Artifact — Vehicle",
        )
        ordinary = _card(db, "Ordinary Creature", type_line="Creature — Human")

        assert commander_eligibility(legendary)[0] is True
        assert commander_eligibility(planeswalker)[0] is True
        assert commander_eligibility(vehicle)[0] is True
        assert commander_eligibility(powerless_vehicle)[0] is False
        assert commander_eligibility(ordinary)[0] is False

        deck = _deck(db, ordinary, [(ordinary, 1)])
        report = analyze_commander_deck(db, deck)

    assert "ineligible_commander" in _codes(report, "legality")


def test_choose_a_background_commander_pair_is_eligible() -> None:
    with SessionLocal() as db:
        leader = _card(
            db, "Background Leader", type_line="Legendary Creature — Human",
            oracle_text="Choose a Background", color_identity="W",
        )
        background = _card(
            db, "Scholar Background", type_line="Legendary Enchantment — Background",
            color_identity="U",
        )
        deck = _deck(db, leader, [(leader, 1)])
        db.add(DeckCard(
            deck_id=deck.id,
            scryfall_id=background.scryfall_id,
            oracle_id=background.oracle_id,
            quantity=1,
            is_commander=True,
            is_sideboard=False,
        ))
        db.flush()
        report = analyze_commander_deck(db, deck)

    assert report["commander"]["count"] == 2
    assert report["commander"]["color_identity"] == ["U", "W"]
    assert "ineligible_commander" not in _codes(report, "legality")
    assert "incompatible_commanders" not in _codes(report, "legality")


def test_availability_aggregates_alternate_printings_and_reports_shortfall() -> None:
    with SessionLocal() as db:
        commander = _card(db, "Leader", type_line="Legendary Creature — Human")
        first = _card(
            db, "Shared Card",
            oracle_text="A deck can have any number of cards named Shared Card.",
        )
        second = _card(db, "Shared Card", oracle=first.oracle)
        missing = _card(db, "Missing Card")
        deck = _deck(db, commander, [(commander, 1), (first, 3), (missing, 1)])
        _hold(db, commander, 1)
        _hold(db, first, 1)
        _hold(db, second, 2)
        report = analyze_commander_deck(db, deck)

        missing_entry = next(dc for dc in deck.cards if dc.oracle_id == missing.oracle_id)
        missing_entry.proxy_quantity = 1
        db.flush()
        proxy_report = analyze_commander_deck(db, deck)

    assert report["available"] is False
    assert report["availability"]["total_shortfall"] == 1
    assert report["availability"]["missing"] == [{
        "oracle_id": missing.oracle_id,
        "name": "Missing Card",
        "required": 1,
        "owned": 0,
        "shortfall": 1,
    }]
    assert proxy_report["available"] is True
    assert proxy_report["availability"]["total_shortfall"] == 0
    assert proxy_report["availability"]["missing"] == []


def test_curve_lands_and_mana_sources() -> None:
    with SessionLocal() as db:
        commander = _card(
            db, "Azorius Leader", type_line="Legendary Creature — Advisor",
            mana_cost="{1}{W}{U}", cmc=3, color_identity="W,U",
        )
        plains = _card(
            db, "Plains", type_line="Basic Land — Plains", mana_cost="", cmc=0,
            color_identity="W", produced_mana=["W"],
        )
        island = _card(
            db, "Island", type_line="Basic Land — Island", mana_cost="", cmc=0,
            color_identity="U", produced_mana=["U"],
        )
        tower = _card(
            db, "Command Tower", type_line="Land", mana_cost="", cmc=0,
            oracle_text="{T}: Add one mana of any color in your commander's color identity.",
            produced_mana=["W", "U"],
        )
        signet = _card(
            db, "Arcane Signet", oracle_text="{T}: Add one mana of any color in your commander's color identity.",
        )
        fetch = _card(
            db, "Evolving Test", type_line="Land", mana_cost="", cmc=0,
            oracle_text="{T}, Sacrifice Evolving Test: Search your library for a basic land card, put it onto the battlefield tapped, then shuffle.",
        )
        expensive = _card(db, "Expensive Spell", mana_cost="{5}{W}{U}", cmc=7, color_identity="W,U")
        deck = _deck(
            db, commander,
            [(commander, 1), (plains, 3), (island, 2), (tower, 1), (signet, 1), (fetch, 1), (expensive, 3)],
        )
        report = analyze_commander_deck(db, deck)

    health = report["health"]
    assert health["lands"]["count"] == 7
    assert health["mana_sources"]["total"] == 8
    assert health["mana_sources"]["by_color"]["W"] == 6
    assert health["mana_sources"]["by_color"]["U"] == 5
    assert health["mana_sources"]["mana_demand"] == {"W": 4, "U": 4, "B": 0, "R": 0, "G": 0}
    assert health["curve"]["buckets"]["3"] == 1
    assert health["curve"]["buckets"]["7+"] == 3
    assert health["curve"]["average_mana_value"] == 5.0
    assert {"low_land_count", "low_mana_sources", "high_average_mana_value"} <= _codes(report, "health")


def test_functional_role_classification() -> None:
    with SessionLocal() as db:
        commander = _card(db, "Leader", type_line="Legendary Creature — Human")
        cards = [
            _card(db, "Ramp", oracle_text="Search your library for a basic land card, put it onto the battlefield tapped, then shuffle."),
            _card(db, "Draw", oracle_text="Draw two cards."),
            _card(db, "Removal", oracle_text="Exile target creature."),
            _card(db, "Wipe", oracle_text="Destroy all creatures."),
            _card(db, "Guard", oracle_text="Creatures you control gain indestructible until end of turn."),
            _card(db, "Return", oracle_text="Return target creature card from your graveyard to the battlefield."),
            _card(db, "Hate", oracle_text="Exile target card from a graveyard."),
            _card(db, "Counter", oracle_text="Counter target spell."),
            _card(db, "Tutor", oracle_text="Search your library for an artifact card, reveal it, then shuffle."),
        ]
        deck = _deck(db, commander, [(commander, 1), *((card, 1) for card in cards)])
        report = analyze_commander_deck(db, deck)

    roles = report["health"]["roles"]
    for role in (
        "ramp", "card_draw", "spot_removal", "board_wipes", "protection",
        "recursion", "graveyard_hate", "counterspells", "tutors",
    ):
        assert roles[role]["count"] == 1, role


def test_analysis_api_is_deterministic(client: TestClient) -> None:
    with SessionLocal() as db:
        commander = _card(db, "API Leader", type_line="Legendary Creature — Human")
        deck = _deck(db, commander, [(commander, 1)])
        deck_id = deck.id
        db.commit()

    first = client.get(f"/api/decks/{deck_id}/analysis")
    second = client.get(f"/api/decks/{deck_id}/analysis")
    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["deterministic"] is True
