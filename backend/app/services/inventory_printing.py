from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CardPrinting, DeckCardAllocation, InventoryLine


class InventoryPrintingError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PrintingCorrectionResult:
    changed_lines: int
    moved_quantity: int
    source_scryfall_id: str
    target_scryfall_id: str


def _same_nullable(query, column, value):
    return query.filter(column == value) if value is not None else query.filter(column.is_(None))


def _destination_line(
    db: Session,
    source: InventoryLine,
    target_scryfall_id: str,
) -> InventoryLine | None:
    query = db.query(InventoryLine).filter(
        InventoryLine.id != source.id,
        InventoryLine.scryfall_id == target_scryfall_id,
        InventoryLine.foil == source.foil,
    )
    query = _same_nullable(query, InventoryLine.condition, source.condition)
    query = _same_nullable(query, InventoryLine.language, source.language)
    return query.first()


def _merge_annotation(destination: InventoryLine, source: InventoryLine) -> None:
    destination.misprint = destination.misprint or source.misprint
    destination.altered = destination.altered or source.altered
    if destination.purchase_price is None:
        destination.purchase_price = source.purchase_price
        destination.purchase_currency = source.purchase_currency
    if destination.manabox_id is None:
        destination.manabox_id = source.manabox_id


def _validate_merge_metadata(destination: InventoryLine, source: InventoryLine) -> None:
    conflicts = []
    if destination.misprint != source.misprint:
        conflicts.append("misprint")
    if destination.altered != source.altered:
        conflicts.append("altered")
    for field in ("purchase_price", "purchase_currency", "manabox_id"):
        left = getattr(destination, field)
        right = getattr(source, field)
        if left is not None and right is not None and left != right:
            conflicts.append(field)
    if conflicts:
        raise InventoryPrintingError(
            "The destination has conflicting inventory metadata: "
            + ", ".join(conflicts),
            status_code=409,
        )


def _move_line(
    db: Session,
    source: InventoryLine,
    target: CardPrinting,
) -> None:
    destination = _destination_line(db, source, target.scryfall_id)
    if destination:
        _validate_merge_metadata(destination, source)
        destination.quantity += source.quantity
        _merge_annotation(destination, source)
        db.delete(source)
    else:
        source.scryfall_id = target.scryfall_id
        source.set_code = target.set_code
        source.collector_number = target.collector_number
    db.flush()


def _remap_exact_allocations(
    db: Session,
    source_scryfall_id: str,
    target_scryfall_id: str,
) -> None:
    rows = db.query(DeckCardAllocation).filter(
        DeckCardAllocation.scryfall_id == source_scryfall_id
    ).all()
    for row in rows:
        destination = db.query(DeckCardAllocation).filter(
            DeckCardAllocation.id != row.id,
            DeckCardAllocation.deck_card_id == row.deck_card_id,
            DeckCardAllocation.status == row.status,
            DeckCardAllocation.scryfall_id == target_scryfall_id,
        ).first()
        if destination:
            destination.quantity += row.quantity
            db.delete(row)
        else:
            row.scryfall_id = target_scryfall_id
    db.flush()


def _validate_target(
    source: CardPrinting,
    target: CardPrinting,
    lines: list[InventoryLine],
    *,
    target_foil: bool,
    target_nonfoil: bool,
    target_language: str | None,
) -> None:
    if source.oracle_id != target.oracle_id:
        raise InventoryPrintingError(
            "The selected printing is not the same Oracle card"
        )
    if any(line.foil for line in lines) and not target_foil:
        raise InventoryPrintingError(
            "The selected printing is not available in foil"
        )
    if any(not line.foil for line in lines) and not target_nonfoil:
        raise InventoryPrintingError(
            "The selected printing is not available in nonfoil"
        )
    mismatched_languages = {
        line.language for line in lines
        if line.language and target_language and line.language != target_language
    }
    if mismatched_languages:
        line_language = sorted(mismatched_languages)[0]
        raise InventoryPrintingError(
            f"The selected printing is {target_language.upper()}, but the inventory "
            f"line is {line_language.upper()}"
        )


def correct_inventory_line_printing(
    db: Session,
    line: InventoryLine,
    target: CardPrinting,
    *,
    target_foil: bool,
    target_nonfoil: bool,
    target_language: str | None,
) -> PrintingCorrectionResult:
    source_id = line.scryfall_id
    if source_id == target.scryfall_id:
        return PrintingCorrectionResult(0, 0, source_id, target.scryfall_id)
    source = db.get(CardPrinting, source_id)
    if source is None:
        raise InventoryPrintingError("Source printing is not cached", status_code=404)
    _validate_target(
        source, target, [line],
        target_foil=target_foil,
        target_nonfoil=target_nonfoil,
        target_language=target_language,
    )
    source_total = sum(
        row.quantity for row in db.query(InventoryLine).filter(
            InventoryLine.scryfall_id == source_id
        ).all()
    )
    exact_grabbed = int(
        db.query(func.coalesce(func.sum(DeckCardAllocation.quantity), 0))
        .filter(
            DeckCardAllocation.scryfall_id == source_id,
            DeckCardAllocation.status == "grabbed",
        )
        .scalar()
        or 0
    )
    exact_allocations = db.query(DeckCardAllocation.id).filter(
        DeckCardAllocation.scryfall_id == source_id
    ).first()
    remaining_source = source_total - line.quantity
    if remaining_source > 0 and remaining_source < exact_grabbed:
        raise InventoryPrintingError(
            "Changing this line would leave fewer copies than its exact grabbed deck "
            "assignments. Change the whole printing, or change those deck assignments first.",
            status_code=409,
        )
    quantity = line.quantity
    _move_line(db, line, target)
    if exact_allocations and remaining_source == 0:
        _remap_exact_allocations(db, source_id, target.scryfall_id)
    return PrintingCorrectionResult(1, quantity, source_id, target.scryfall_id)


def correct_inventory_printing(
    db: Session,
    source: CardPrinting,
    target: CardPrinting,
    *,
    target_foil: bool,
    target_nonfoil: bool,
    target_language: str | None,
) -> PrintingCorrectionResult:
    source_id = source.scryfall_id
    if source_id == target.scryfall_id:
        return PrintingCorrectionResult(0, 0, source_id, target.scryfall_id)
    lines = db.query(InventoryLine).filter(
        InventoryLine.scryfall_id == source_id
    ).order_by(InventoryLine.id).all()
    if not lines:
        raise InventoryPrintingError("Inventory printing not found", status_code=404)
    _validate_target(
        source, target, lines,
        target_foil=target_foil,
        target_nonfoil=target_nonfoil,
        target_language=target_language,
    )
    for line in lines:
        destination = _destination_line(db, line, target.scryfall_id)
        if destination:
            _validate_merge_metadata(destination, line)
    quantity = sum(line.quantity for line in lines)
    changed_lines = len(lines)
    for line in lines:
        _move_line(db, line, target)
    _remap_exact_allocations(db, source_id, target.scryfall_id)
    return PrintingCorrectionResult(
        changed_lines, quantity, source_id, target.scryfall_id
    )
