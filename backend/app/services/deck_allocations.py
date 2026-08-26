from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CardPrinting, DeckCard, DeckCardAllocation, InventoryLine


ALLOCATION_STATUSES = ("pending", "grabbed", "proxy")


class AllocationError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AllocationSpec:
    status: str
    quantity: int
    scryfall_id: str | None = None
    foil: bool | None = None


def _owned_printing_quantity(db: Session, scryfall_id: str) -> int:
    return int(
        db.query(func.coalesce(func.sum(InventoryLine.quantity), 0))
        .filter(InventoryLine.scryfall_id == scryfall_id)
        .scalar()
        or 0
    )


def _owned_oracle_quantity(db: Session, oracle_id: str) -> int:
    return int(
        db.query(func.coalesce(func.sum(InventoryLine.quantity), 0))
        .join(CardPrinting, InventoryLine.scryfall_id == CardPrinting.scryfall_id)
        .filter(CardPrinting.oracle_id == oracle_id)
        .scalar()
        or 0
    )


def _merge_inventory_default(db: Session, scryfall_id: str, quantity: int) -> None:
    if quantity <= 0:
        return
    existing = (
        db.query(InventoryLine)
        .filter(
            InventoryLine.scryfall_id == scryfall_id,
            InventoryLine.foil.is_(False),
            InventoryLine.condition.is_(None),
            InventoryLine.language == "en",
        )
        .first()
    )
    if existing:
        existing.quantity += quantity
    else:
        db.add(InventoryLine(
            scryfall_id=scryfall_id,
            quantity=quantity,
            foil=False,
            condition=None,
            language="en",
        ))
    db.flush()


def ensure_deck_card_allocations(db: Session, deck_card: DeckCard) -> None:
    if db.query(DeckCardAllocation.id).filter(
        DeckCardAllocation.deck_card_id == deck_card.id
    ).first():
        return
    pending = deck_card.quantity - deck_card.grabbed_quantity - deck_card.proxy_quantity
    if deck_card.grabbed_quantity > 0:
        db.add(DeckCardAllocation(
            deck_card_id=deck_card.id,
            scryfall_id=deck_card.scryfall_id,
            status="grabbed",
            quantity=deck_card.grabbed_quantity,
        ))
    if deck_card.proxy_quantity > 0:
        db.add(DeckCardAllocation(
            deck_card_id=deck_card.id,
            scryfall_id=deck_card.scryfall_id,
            status="proxy",
            quantity=deck_card.proxy_quantity,
        ))
    if pending > 0:
        db.add(DeckCardAllocation(
            deck_card_id=deck_card.id,
            scryfall_id=None,
            status="pending",
            quantity=pending,
        ))
    db.flush()


def add_allocation_quantity(
    db: Session,
    deck_card: DeckCard,
    *,
    status: str,
    quantity: int,
    scryfall_id: str | None,
    foil: bool | None = None,
) -> None:
    if quantity <= 0:
        return
    if status not in ALLOCATION_STATUSES:
        raise AllocationError(f"Unknown allocation status: {status}")
    query = db.query(DeckCardAllocation).filter(
        DeckCardAllocation.deck_card_id == deck_card.id,
        DeckCardAllocation.status == status,
    )
    query = query.filter(
        DeckCardAllocation.scryfall_id == scryfall_id
        if scryfall_id is not None
        else DeckCardAllocation.scryfall_id.is_(None)
    )
    query = query.filter(
        DeckCardAllocation.foil == foil
        if foil is not None
        else DeckCardAllocation.foil.is_(None)
    )
    existing = query.first()
    if existing:
        existing.quantity += quantity
    else:
        db.add(DeckCardAllocation(
            deck_card_id=deck_card.id,
            scryfall_id=scryfall_id,
            status=status,
            quantity=quantity,
            foil=foil if scryfall_id is not None else None,
        ))
    db.flush()


def _normalized_specs(specs: list[AllocationSpec]) -> list[AllocationSpec]:
    combined: Counter[tuple[str, str | None, bool | None]] = Counter()
    for spec in specs:
        if spec.status not in ALLOCATION_STATUSES:
            raise AllocationError(f"Unknown allocation status: {spec.status}")
        if spec.quantity <= 0:
            raise AllocationError("Allocation quantities must be positive")
        if spec.foil is not None and spec.scryfall_id is None:
            raise AllocationError("A foil treatment requires an exact printing")
        combined[(spec.status, spec.scryfall_id, spec.foil)] += spec.quantity
    return [
        AllocationSpec(
            status=status,
            scryfall_id=scryfall_id,
            foil=foil,
            quantity=quantity,
        )
        for (status, scryfall_id, foil), quantity in sorted(
            combined.items(),
            key=lambda item: (item[0][0], item[0][1] or "", str(item[0][2])),
        )
    ]


def _validate_specs(
    db: Session,
    deck_card: DeckCard,
    specs: list[AllocationSpec],
) -> list[AllocationSpec]:
    normalized = _normalized_specs(specs)
    total = sum(spec.quantity for spec in normalized)
    if total != deck_card.quantity:
        raise AllocationError(
            f"Allocation quantities must total {deck_card.quantity}; received {total}"
        )
    printing_ids = {spec.scryfall_id for spec in normalized if spec.scryfall_id}
    if printing_ids:
        printings = {
            printing.scryfall_id: printing
            for printing in db.query(CardPrinting).filter(
                CardPrinting.scryfall_id.in_(printing_ids)
            ).all()
        }
        missing = printing_ids - set(printings)
        if missing:
            raise AllocationError("One or more selected printings are not cached")
        wrong = [
            printing.scryfall_id for printing in printings.values()
            if printing.oracle_id != deck_card.oracle_id
        ]
        if wrong:
            raise AllocationError("Selected printing does not match this deck card")
    return normalized


def _reconcile_grabbed_inventory(
    db: Session,
    deck_card: DeckCard,
    specs: list[AllocationSpec],
) -> None:
    exact_target: Counter[str] = Counter()
    treatment_target: Counter[tuple[str, bool]] = Counter()
    target_grabbed = 0
    for spec in specs:
        if spec.status != "grabbed":
            continue
        target_grabbed += spec.quantity
        if spec.scryfall_id:
            exact_target[spec.scryfall_id] += spec.quantity
            if spec.foil is not None:
                treatment_target[(spec.scryfall_id, spec.foil)] += spec.quantity

    for scryfall_id, target_quantity in exact_target.items():
        other_exact = int(
            db.query(func.coalesce(func.sum(DeckCardAllocation.quantity), 0))
            .filter(
                DeckCardAllocation.deck_card_id != deck_card.id,
                DeckCardAllocation.scryfall_id == scryfall_id,
                DeckCardAllocation.status == "grabbed",
            )
            .scalar()
            or 0
        )
        owned = _owned_printing_quantity(db, scryfall_id)
        if other_exact + target_quantity > owned:
            raise AllocationError(
                f"That printing has {owned} owned copy/copies, with {other_exact} "
                "already assigned to other decks",
                status_code=409,
            )

    for (scryfall_id, foil), target_quantity in treatment_target.items():
        other_treatment = int(
            db.query(func.coalesce(func.sum(DeckCardAllocation.quantity), 0))
            .filter(
                DeckCardAllocation.deck_card_id != deck_card.id,
                DeckCardAllocation.scryfall_id == scryfall_id,
                DeckCardAllocation.status == "grabbed",
                DeckCardAllocation.foil.is_(foil),
            )
            .scalar()
            or 0
        )
        owned_treatment = int(
            db.query(func.coalesce(func.sum(InventoryLine.quantity), 0))
            .filter(
                InventoryLine.scryfall_id == scryfall_id,
                InventoryLine.foil.is_(foil),
            )
            .scalar()
            or 0
        )
        if other_treatment + target_quantity > owned_treatment:
            label = "foil" if foil else "nonfoil"
            raise AllocationError(
                f"That printing has {owned_treatment} owned {label} copy/copies, "
                f"with {other_treatment} already assigned to other decks",
                status_code=409,
            )

    current_rows = db.query(DeckCardAllocation).filter(
        DeckCardAllocation.deck_card_id == deck_card.id
    ).all()
    current_any_grabbed = sum(
        row.quantity for row in current_rows
        if row.status == "grabbed" and row.scryfall_id is None
    )
    target_any_grabbed = sum(
        spec.quantity for spec in specs
        if spec.status == "grabbed" and spec.scryfall_id is None
    )
    any_grabbed_increase = max(0, target_any_grabbed - current_any_grabbed)
    if any_grabbed_increase > 0:
        # Any-printing assembly keeps the existing behavior: marking a copy as
        # physically grabbed is an assertion of ownership and reconciles the
        # collection. Pending demand in other decks remains earmarked.
        owned_total = _owned_oracle_quantity(db, deck_card.oracle_id)
        grabbed_before = int(
            db.query(func.coalesce(func.sum(DeckCard.grabbed_quantity), 0))
            .filter(DeckCard.oracle_id == deck_card.oracle_id)
            .scalar()
            or 0
        )
        bulk = max(0, owned_total - grabbed_before)
        old_pending = (
            deck_card.quantity - deck_card.grabbed_quantity - deck_card.proxy_quantity
        )
        new_proxy = sum(spec.quantity for spec in specs if spec.status == "proxy")
        new_pending = deck_card.quantity - target_grabbed - new_proxy
        converted_pending = min(
            any_grabbed_increase, max(0, old_pending - new_pending)
        )
        claimed_earmark = min(converted_pending, bulk)
        pending_before = int(
            db.query(func.coalesce(func.sum(
                DeckCard.quantity - DeckCard.grabbed_quantity - DeckCard.proxy_quantity
            ), 0))
            .filter(DeckCard.oracle_id == deck_card.oracle_id)
            .scalar()
            or 0
        )
        other_pending = max(0, pending_before - converted_pending)
        genuinely_free = max(0, bulk - claimed_earmark - other_pending)
        available = claimed_earmark + min(
            any_grabbed_increase - claimed_earmark, genuinely_free
        )
        if any_grabbed_increase > available:
            _merge_inventory_default(
                db, deck_card.scryfall_id, any_grabbed_increase - available
            )

    other_grabbed = int(
        db.query(func.coalesce(func.sum(DeckCard.grabbed_quantity), 0))
        .filter(
            DeckCard.oracle_id == deck_card.oracle_id,
            DeckCard.id != deck_card.id,
        )
        .scalar()
        or 0
    )
    owned_after_reconcile = _owned_oracle_quantity(db, deck_card.oracle_id)
    if other_grabbed + target_grabbed > owned_after_reconcile:
        raise AllocationError(
            f"This card has {owned_after_reconcile} owned copy/copies, with "
            f"{other_grabbed} already grabbed in other decks",
            status_code=409,
        )


def replace_deck_card_allocations(
    db: Session,
    deck_card: DeckCard,
    specs: list[AllocationSpec],
) -> None:
    normalized = _validate_specs(db, deck_card, specs)
    _reconcile_grabbed_inventory(db, deck_card, normalized)

    for row in db.query(DeckCardAllocation).filter(
        DeckCardAllocation.deck_card_id == deck_card.id
    ).all():
        db.delete(row)
    db.flush()
    for spec in normalized:
        db.add(DeckCardAllocation(
            deck_card_id=deck_card.id,
            scryfall_id=spec.scryfall_id,
            status=spec.status,
            quantity=spec.quantity,
            foil=spec.foil,
        ))
    deck_card.grabbed_quantity = sum(
        spec.quantity for spec in normalized if spec.status == "grabbed"
    )
    deck_card.proxy_quantity = sum(
        spec.quantity for spec in normalized if spec.status == "proxy"
    )
    db.flush()


def set_deck_card_status_counts(
    db: Session,
    deck_card: DeckCard,
    *,
    grabbed_quantity: int,
    proxy_quantity: int,
) -> None:
    pending_quantity = deck_card.quantity - grabbed_quantity - proxy_quantity
    if min(grabbed_quantity, proxy_quantity, pending_quantity) < 0:
        raise AllocationError(
            "Grabbed and proxy quantities cannot exceed the deck quantity"
        )
    ensure_deck_card_allocations(db, deck_card)
    rows = db.query(DeckCardAllocation).filter(
        DeckCardAllocation.deck_card_id == deck_card.id
    ).order_by(DeckCardAllocation.id).all()
    units_by_status: dict[str, list[tuple[str | None, bool | None]]] = {
        status: [] for status in ALLOCATION_STATUSES
    }
    for row in rows:
        units_by_status[row.status].extend(
            [(row.scryfall_id, row.foil)] * row.quantity
        )

    targets = {
        "pending": pending_quantity,
        "grabbed": grabbed_quantity,
        "proxy": proxy_quantity,
    }
    kept: dict[str, list[tuple[str | None, bool | None]]] = {}
    surplus: list[tuple[str | None, bool | None]] = []
    for status in ALLOCATION_STATUSES:
        current = units_by_status[status]
        keep_count = min(len(current), targets[status])
        kept[status] = current[:keep_count]
        surplus.extend(current[keep_count:])
    for status in ALLOCATION_STATUSES:
        deficit = targets[status] - len(kept[status])
        if deficit > 0:
            kept[status].extend(surplus[:deficit])
            del surplus[:deficit]
    if surplus:
        raise AllocationError("Could not redistribute deck allocation quantities")

    specs = [
        AllocationSpec(
            status=status,
            scryfall_id=scryfall_id,
            foil=foil,
            quantity=quantity,
        )
        for status in ALLOCATION_STATUSES
        for (scryfall_id, foil), quantity in Counter(kept[status]).items()
    ]
    replace_deck_card_allocations(db, deck_card, specs)
