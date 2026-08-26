from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import (
    CardPrinting,
    Deck,
    DeckCard,
    DeckCardAllocation,
    InventoryLine,
    OracleCard,
)
from app.services.deck_allocations import (
    AllocationError,
    AllocationSpec,
    ensure_deck_card_allocations,
    replace_deck_card_allocations,
    set_deck_card_status_counts,
)


ORACLE_ID = "30000000-0000-4000-8000-000000000001"
OTHER_ORACLE_ID = "30000000-0000-4000-8000-000000000002"
PRINTING_A = "40000000-0000-4000-8000-000000000001"
PRINTING_B = "40000000-0000-4000-8000-000000000002"
WRONG_PRINTING = "40000000-0000-4000-8000-000000000003"


def _seed_cards(db) -> None:
    oracle = OracleCard(
        oracle_id=ORACLE_ID,
        name="Allocation Test Card",
        type_line="Artifact",
        cmc=2,
        colors="",
        color_identity="",
        legalities_json='{"commander":"legal"}',
    )
    other_oracle = OracleCard(
        oracle_id=OTHER_ORACLE_ID,
        name="Wrong Oracle Card",
        type_line="Creature",
        cmc=2,
        colors="G",
        color_identity="G",
        legalities_json='{"commander":"legal"}',
    )
    db.add_all([
        CardPrinting(scryfall_id=PRINTING_A, oracle=oracle, set_code="aaa"),
        CardPrinting(scryfall_id=PRINTING_B, oracle=oracle, set_code="bbb"),
        CardPrinting(
            scryfall_id=WRONG_PRINTING,
            oracle=other_oracle,
            set_code="ccc",
        ),
    ])
    db.flush()


def _add_deck_card(db, *, quantity: int = 1, name: str = "Test Deck") -> DeckCard:
    deck = Deck(name=name, format="commander", status="building")
    db.add(deck)
    db.flush()
    deck_card = DeckCard(
        deck_id=deck.id,
        scryfall_id=PRINTING_A,
        oracle_id=ORACLE_ID,
        quantity=quantity,
        grabbed_quantity=0,
        proxy_quantity=0,
        is_commander=False,
        is_sideboard=False,
    )
    db.add(deck_card)
    db.flush()
    return deck_card


def _allocation_tuples(db, deck_card_id: int) -> set[tuple[str, str | None, int]]:
    return {
        (row.status, row.scryfall_id, row.quantity)
        for row in db.query(DeckCardAllocation).filter(
            DeckCardAllocation.deck_card_id == deck_card_id
        )
    }


def test_missing_allocations_backfill_pending_as_any_printing() -> None:
    with SessionLocal() as db:
        _seed_cards(db)
        deck_card = _add_deck_card(db, quantity=3)

        ensure_deck_card_allocations(db, deck_card)
        ensure_deck_card_allocations(db, deck_card)

        assert _allocation_tuples(db, deck_card.id) == {("pending", None, 3)}


def test_replace_allocations_supports_exact_and_any_printings() -> None:
    with SessionLocal() as db:
        _seed_cards(db)
        deck_card = _add_deck_card(db, quantity=3)
        db.add(InventoryLine(
            scryfall_id=PRINTING_A,
            quantity=1,
            foil=False,
            language="en",
        ))
        db.flush()

        replace_deck_card_allocations(db, deck_card, [
            AllocationSpec(status="grabbed", scryfall_id=PRINTING_A, quantity=1),
            AllocationSpec(status="pending", scryfall_id=None, quantity=1),
            AllocationSpec(status="proxy", scryfall_id=PRINTING_B, quantity=1),
        ])

        assert deck_card.grabbed_quantity == 1
        assert deck_card.proxy_quantity == 1
        assert _allocation_tuples(db, deck_card.id) == {
            ("grabbed", PRINTING_A, 1),
            ("pending", None, 1),
            ("proxy", PRINTING_B, 1),
        }


def test_replace_allocations_rejects_wrong_oracle_and_bad_total() -> None:
    with SessionLocal() as db:
        _seed_cards(db)
        deck_card = _add_deck_card(db, quantity=2)

        with pytest.raises(AllocationError, match="must total 2"):
            replace_deck_card_allocations(db, deck_card, [
                AllocationSpec(status="pending", quantity=1),
            ])
        with pytest.raises(AllocationError, match="does not match"):
            replace_deck_card_allocations(db, deck_card, [
                AllocationSpec(
                    status="pending",
                    scryfall_id=WRONG_PRINTING,
                    quantity=2,
                ),
            ])

        assert db.query(DeckCardAllocation).count() == 0
        assert deck_card.grabbed_quantity == 0
        assert deck_card.proxy_quantity == 0


def test_exact_grabbed_printing_cannot_be_assigned_to_two_decks() -> None:
    with SessionLocal() as db:
        _seed_cards(db)
        first = _add_deck_card(db, name="First Deck")
        second = _add_deck_card(db, name="Second Deck")
        db.add(InventoryLine(
            scryfall_id=PRINTING_A,
            quantity=1,
            foil=False,
            language="en",
        ))
        db.flush()

        replace_deck_card_allocations(db, first, [
            AllocationSpec(status="grabbed", scryfall_id=PRINTING_A, quantity=1),
        ])
        with pytest.raises(AllocationError, match="already assigned"):
            replace_deck_card_allocations(db, second, [
                AllocationSpec(
                    status="grabbed",
                    scryfall_id=PRINTING_A,
                    quantity=1,
                ),
            ])

        assert _allocation_tuples(db, first.id) == {("grabbed", PRINTING_A, 1)}
        assert _allocation_tuples(db, second.id) == set()


def test_exact_printing_allocations_distinguish_foil_treatments() -> None:
    with SessionLocal() as db:
        _seed_cards(db)
        nonfoil_deck = _add_deck_card(db, name="Nonfoil Deck")
        foil_deck = _add_deck_card(db, name="Foil Deck")
        extra_foil_deck = _add_deck_card(db, name="Extra Foil Deck")
        db.add_all([
                InventoryLine(
                    scryfall_id=PRINTING_A,
                    quantity=2,
                    foil=False,
                language="en",
            ),
            InventoryLine(
                scryfall_id=PRINTING_A,
                quantity=1,
                foil=True,
                language="en",
            ),
        ])
        db.flush()

        replace_deck_card_allocations(db, nonfoil_deck, [
            AllocationSpec(
                status="grabbed", scryfall_id=PRINTING_A, foil=False, quantity=1
            ),
        ])
        replace_deck_card_allocations(db, foil_deck, [
            AllocationSpec(
                status="grabbed", scryfall_id=PRINTING_A, foil=True, quantity=1
            ),
        ])
        with pytest.raises(AllocationError, match="owned foil") as error:
            replace_deck_card_allocations(db, extra_foil_deck, [
                AllocationSpec(
                    status="grabbed", scryfall_id=PRINTING_A, foil=True, quantity=1
                ),
            ])

        assert error.value.status_code == 409
        rows = db.query(DeckCardAllocation).filter(
            DeckCardAllocation.deck_card_id.in_([nonfoil_deck.id, foil_deck.id])
        ).all()
        assert {(row.deck_card_id, row.foil) for row in rows} == {
            (nonfoil_deck.id, False),
            (foil_deck.id, True),
        }


def test_treatment_requires_an_exact_printing() -> None:
    with SessionLocal() as db:
        _seed_cards(db)
        deck_card = _add_deck_card(db)
        with pytest.raises(AllocationError, match="requires an exact printing"):
            replace_deck_card_allocations(db, deck_card, [
                AllocationSpec(status="pending", foil=True, quantity=1),
            ])


def test_aggregate_status_update_preserves_any_printing_compatibility() -> None:
    with SessionLocal() as db:
        _seed_cards(db)
        deck_card = _add_deck_card(db, quantity=2)
        ensure_deck_card_allocations(db, deck_card)

        set_deck_card_status_counts(
            db,
            deck_card,
            grabbed_quantity=1,
            proxy_quantity=1,
        )

        assert deck_card.grabbed_quantity == 1
        assert deck_card.proxy_quantity == 1
        assert _allocation_tuples(db, deck_card.id) == {
            ("grabbed", None, 1),
            ("proxy", None, 1),
        }
        assert db.query(InventoryLine).filter(
            InventoryLine.scryfall_id == PRINTING_A
        ).one().quantity == 1


def test_exact_grabbed_cannot_overallocate_an_any_grabbed_copy() -> None:
    with SessionLocal() as db:
        _seed_cards(db)
        first = _add_deck_card(db, name="Any Grabbed Deck")
        second = _add_deck_card(db, name="Exact Grabbed Deck")
        db.add(InventoryLine(
            scryfall_id=PRINTING_A,
            quantity=1,
            foil=False,
            language="en",
        ))
        db.flush()
        ensure_deck_card_allocations(db, first)
        set_deck_card_status_counts(
            db,
            first,
            grabbed_quantity=1,
            proxy_quantity=0,
        )

        with pytest.raises(AllocationError, match="already grabbed") as error:
            replace_deck_card_allocations(db, second, [
                AllocationSpec(
                    status="grabbed",
                    scryfall_id=PRINTING_A,
                    quantity=1,
                ),
            ])

        assert error.value.status_code == 409
        assert _allocation_tuples(db, first.id) == {("grabbed", None, 1)}
        assert _allocation_tuples(db, second.id) == set()
