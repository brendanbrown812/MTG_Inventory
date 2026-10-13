from __future__ import annotations

import csv
import io
from collections import Counter

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import CardPrinting, DeckCard, DeckCardAllocation, InventoryLine


MOXFIELD_HEADERS = (
    "Count",
    "Tradelist Count",
    "Name",
    "Edition",
    "Condition",
    "Language",
    "Foil",
    "Tags",
    "Last Modified",
    "Collector Number",
    "Alter",
    "Proxy",
    "Purchase Price",
)

_CONDITIONS = {
    "mint": "Mint",
    "near_mint": "Near Mint",
    "near mint": "Near Mint",
    "excellent": "Near Mint",
    "good": "Good (Lightly Played)",
    "lightly_played": "Good (Lightly Played)",
    "lightly played": "Good (Lightly Played)",
    "played": "Played",
    "moderately_played": "Played",
    "moderately played": "Played",
    "heavily_played": "Heavily Played",
    "heavily played": "Heavily Played",
    "poor": "Damaged",
    "damaged": "Damaged",
}

_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "ru": "Russian",
    "zhs": "Simplified Chinese",
    "zht": "Traditional Chinese",
    "he": "Hebrew",
    "la": "Latin",
    "grc": "Ancient Greek",
    "ar": "Arabic",
    "sa": "Sanskrit",
    "ph": "Phyrexian",
}


def _condition(value: str | None) -> str:
    if not value:
        return ""
    return _CONDITIONS.get(value.strip().casefold(), value.strip())


def _language(value: str | None) -> str:
    if not value:
        return ""
    return _LANGUAGES.get(value.strip().casefold(), value.strip())


def build_available_collection_csv(db: Session) -> tuple[str, int, int]:
    """Return a Moxfield-compatible CSV containing only unreserved physical copies."""
    lines = (
        db.query(InventoryLine)
        .join(CardPrinting, InventoryLine.scryfall_id == CardPrinting.scryfall_id)
        .options(joinedload(InventoryLine.card).joinedload(CardPrinting.oracle))
        .filter(InventoryLine.quantity > 0)
        .order_by(InventoryLine.id)
        .all()
    )
    remaining = {line.id: line.quantity for line in lines}
    lines_by_oracle: dict[str, list[InventoryLine]] = {}
    for line in lines:
        lines_by_oracle.setdefault(line.card.oracle_id, []).append(line)

    reserved_by_oracle = {
        oracle_id: int(quantity or 0)
        for oracle_id, quantity in (
            db.query(
                DeckCard.oracle_id,
                func.sum(DeckCard.quantity - DeckCard.proxy_quantity),
            )
            .group_by(DeckCard.oracle_id)
            .all()
        )
    }
    exact_allocations = (
        db.query(
            DeckCard.oracle_id,
            DeckCardAllocation.scryfall_id,
            DeckCardAllocation.foil,
            func.sum(DeckCardAllocation.quantity),
        )
        .join(DeckCard, DeckCard.id == DeckCardAllocation.deck_card_id)
        .filter(
            DeckCardAllocation.status != "proxy",
            DeckCardAllocation.scryfall_id.is_not(None),
        )
        .group_by(
            DeckCard.oracle_id,
            DeckCardAllocation.scryfall_id,
            DeckCardAllocation.foil,
        )
        .order_by(
            DeckCard.oracle_id,
            DeckCardAllocation.scryfall_id,
            DeckCardAllocation.foil,
        )
        .all()
    )

    deducted_exact: Counter[str] = Counter()
    for oracle_id, scryfall_id, foil, quantity in exact_allocations:
        needed = int(quantity or 0)
        candidates = [
            line
            for line in lines_by_oracle.get(oracle_id, [])
            if line.scryfall_id == scryfall_id and (foil is None or line.foil is foil)
        ]
        for line in candidates:
            removed = min(remaining[line.id], needed)
            remaining[line.id] -= removed
            deducted_exact[oracle_id] += removed
            needed -= removed
            if needed == 0:
                break

    for oracle_id, reserved in reserved_by_oracle.items():
        needed = max(0, reserved - deducted_exact[oracle_id])
        for line in lines_by_oracle.get(oracle_id, []):
            removed = min(remaining[line.id], needed)
            remaining[line.id] -= removed
            needed -= removed
            if needed == 0:
                break

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(MOXFIELD_HEADERS)
    exported_rows = 0
    exported_cards = 0
    for line in lines:
        quantity = remaining[line.id]
        if quantity <= 0:
            continue
        printing = line.card
        writer.writerow((
            quantity,
            "",
            printing.name,
            printing.set_code or line.set_code or "",
            _condition(line.condition),
            _language(line.language or printing.language),
            "foil" if line.foil else "",
            "",
            "",
            printing.collector_number or line.collector_number or "",
            "True" if line.altered else "False",
            "False",
            "" if line.purchase_price is None else line.purchase_price,
        ))
        exported_rows += 1
        exported_cards += quantity
    return output.getvalue(), exported_rows, exported_cards
