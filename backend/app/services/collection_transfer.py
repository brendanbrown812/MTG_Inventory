from __future__ import annotations

import base64
import binascii
from collections import Counter
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    CardPrinting,
    DeckCard,
    DeckCardAllocation,
    InventoryLine,
    MechanicProfileRecord,
    OracleCard,
    OracleEmbeddingRecord,
    RecommendationCardPreference,
)
from app.schemas import CollectionBackup, CollectionImportResult


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def build_collection_backup(db: Session) -> CollectionBackup:
    inventory_lines = db.query(InventoryLine).order_by(InventoryLine.id).all()
    printing_ids = sorted({line.scryfall_id for line in inventory_lines})
    printings = (
        db.query(CardPrinting)
        .filter(CardPrinting.scryfall_id.in_(printing_ids))
        .order_by(CardPrinting.scryfall_id)
        .all()
        if printing_ids else []
    )
    oracle_ids = sorted({printing.oracle_id for printing in printings})
    oracle_cards = (
        db.query(OracleCard)
        .filter(OracleCard.oracle_id.in_(oracle_ids))
        .order_by(OracleCard.oracle_id)
        .all()
        if oracle_ids else []
    )
    mechanic_profiles = (
        db.query(MechanicProfileRecord)
        .filter(MechanicProfileRecord.oracle_id.in_(oracle_ids))
        .order_by(MechanicProfileRecord.oracle_id, MechanicProfileRecord.id)
        .all()
        if oracle_ids else []
    )
    embeddings = (
        db.query(OracleEmbeddingRecord)
        .filter(OracleEmbeddingRecord.oracle_id.in_(oracle_ids))
        .order_by(OracleEmbeddingRecord.oracle_id, OracleEmbeddingRecord.id)
        .all()
        if oracle_ids else []
    )
    preferences = (
        db.query(RecommendationCardPreference)
        .filter(RecommendationCardPreference.oracle_id.in_(oracle_ids))
        .order_by(RecommendationCardPreference.oracle_id)
        .all()
        if oracle_ids else []
    )

    return CollectionBackup.model_validate({
        "format": "spellbinder.collection",
        "version": 1,
        "exported_at": _utcnow(),
        "oracle_cards": [{
            "oracle_id": card.oracle_id,
            "name": card.name,
            "type_line": card.type_line,
            "oracle_text": card.oracle_text,
            "mana_cost": card.mana_cost,
            "cmc": card.cmc,
            "colors": card.colors,
            "color_identity": card.color_identity,
            "legalities_json": card.legalities_json,
            "keywords": card.keywords,
            "synergy_tags": card.synergy_tags,
            "tagged_at": card.tagged_at,
            "updated_at": card.updated_at,
        } for card in oracle_cards],
        "printings": [{
            "scryfall_id": printing.scryfall_id,
            "oracle_id": printing.oracle_id,
            "set_code": printing.set_code,
            "collector_number": printing.collector_number,
            "rarity": printing.rarity,
            "language": printing.language,
            "image_uri_normal": printing.image_uri_normal,
            "scryfall_json": printing.scryfall_json,
            "updated_at": printing.updated_at,
        } for printing in printings],
        "inventory_lines": [{
            "scryfall_id": line.scryfall_id,
            "quantity": line.quantity,
            "foil": line.foil,
            "misprint": line.misprint,
            "altered": line.altered,
            "condition": line.condition,
            "language": line.language,
            "set_code": line.set_code,
            "collector_number": line.collector_number,
            "purchase_price": line.purchase_price,
            "purchase_currency": line.purchase_currency,
            "manabox_id": line.manabox_id,
        } for line in inventory_lines],
        "mechanic_profiles": [{
            "oracle_id": profile.oracle_id,
            "schema_version": profile.schema_version,
            "taxonomy_version": profile.taxonomy_version,
            "profile_json": profile.profile_json,
            "provider": profile.provider,
            "model": profile.model,
            "confidence": profile.confidence,
            "is_current": profile.is_current,
            "input_tokens": profile.input_tokens,
            "output_tokens": profile.output_tokens,
            "created_at": profile.created_at,
        } for profile in mechanic_profiles],
        "embeddings": [{
            "oracle_id": embedding.oracle_id,
            "provider": embedding.provider,
            "model": embedding.model,
            "index_version": embedding.index_version,
            "dimensions": embedding.dimensions,
            "source_hash": embedding.source_hash,
            "vector_base64": base64.b64encode(embedding.vector).decode("ascii"),
            "is_current": embedding.is_current,
            "input_tokens": embedding.input_tokens,
            "created_at": embedding.created_at,
        } for embedding in embeddings],
        "card_preferences": [{
            "oracle_id": preference.oracle_id,
            "accepted_count": preference.accepted_count,
            "rejected_count": preference.rejected_count,
            "updated_at": preference.updated_at,
        } for preference in preferences],
    })


def parse_collection_backup(raw_json: bytes) -> CollectionBackup:
    try:
        return CollectionBackup.model_validate_json(raw_json)
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(value) for value in first.get("loc", ()))
        message = first.get("msg", "invalid value")
        detail = f"Invalid Spellbinder collection backup at {location}: {message}"
        raise HTTPException(400, detail=detail) from exc


def _validate_grabbed_cards_against_backup(
    db: Session,
    backup: CollectionBackup,
) -> None:
    """Reject snapshots that cannot support current physical deck locations."""
    printing_oracles = {
        printing.scryfall_id: printing.oracle_id for printing in backup.printings
    }
    card_names = {card.oracle_id: card.name for card in backup.oracle_cards}
    owned_by_oracle: Counter[str] = Counter()
    owned_by_printing: Counter[str] = Counter()
    owned_by_treatment: Counter[tuple[str, bool]] = Counter()
    for line in backup.inventory_lines:
        oracle_id = printing_oracles[line.scryfall_id]
        owned_by_oracle[oracle_id] += line.quantity
        owned_by_printing[line.scryfall_id] += line.quantity
        owned_by_treatment[(line.scryfall_id, line.foil)] += line.quantity

    conflicts: list[str] = []
    grabbed_by_oracle = (
        db.query(
            DeckCard.oracle_id,
            func.coalesce(func.sum(DeckCard.grabbed_quantity), 0),
        )
        .filter(DeckCard.grabbed_quantity > 0)
        .group_by(DeckCard.oracle_id)
        .all()
    )
    for oracle_id, grabbed in grabbed_by_oracle:
        grabbed = int(grabbed or 0)
        owned = owned_by_oracle[oracle_id]
        if owned < grabbed:
            name = card_names.get(oracle_id) or oracle_id
            conflicts.append(f"{name}: {grabbed} grabbed, but the snapshot contains {owned}")

    exact_grabbed = (
        db.query(
            DeckCardAllocation.scryfall_id,
            DeckCardAllocation.foil,
            func.coalesce(func.sum(DeckCardAllocation.quantity), 0),
        )
        .filter(
            DeckCardAllocation.status == "grabbed",
            DeckCardAllocation.scryfall_id.is_not(None),
        )
        .group_by(DeckCardAllocation.scryfall_id, DeckCardAllocation.foil)
        .all()
    )
    printing_names = {
        printing.scryfall_id: card_names.get(printing.oracle_id, printing.scryfall_id)
        for printing in backup.printings
    }
    exact_totals: Counter[str] = Counter()
    for scryfall_id, _foil, quantity in exact_grabbed:
        exact_totals[scryfall_id] += int(quantity or 0)
    for scryfall_id, grabbed in exact_totals.items():
        owned = owned_by_printing[scryfall_id]
        if owned < grabbed:
            name = printing_names.get(scryfall_id, scryfall_id)
            conflicts.append(
                f"{name} exact printing {scryfall_id}: {grabbed} grabbed, "
                f"but the snapshot contains {owned}"
            )
    for scryfall_id, foil, quantity in exact_grabbed:
        if foil is None:
            continue
        grabbed = int(quantity or 0)
        owned = owned_by_treatment[(scryfall_id, bool(foil))]
        if owned < grabbed:
            name = printing_names.get(scryfall_id, scryfall_id)
            treatment = "foil" if foil else "nonfoil"
            conflicts.append(
                f"{name} exact {treatment} printing: {grabbed} grabbed, "
                f"but the snapshot contains {owned}"
            )

    if conflicts:
        shown = "; ".join(conflicts[:5])
        remainder = len(conflicts) - 5
        if remainder > 0:
            shown += f"; and {remainder} more conflict(s)"
        raise HTTPException(
            409,
            detail=(
                "Collection restore was not applied because it would leave grabbed deck "
                f"cards without physical copies. {shown}. Move those deck copies to Needed "
                "or Proxy, or restore a snapshot containing enough copies."
            ),
        )


def restore_collection_backup(db: Session, backup: CollectionBackup) -> CollectionImportResult:
    oracle_ids = {card.oracle_id for card in backup.oracle_cards}
    printing_ids = {printing.scryfall_id for printing in backup.printings}
    if any(printing.oracle_id not in oracle_ids for printing in backup.printings):
        raise HTTPException(400, detail="A printing references an Oracle card missing from the backup")
    if any(line.scryfall_id not in printing_ids for line in backup.inventory_lines):
        raise HTTPException(400, detail="An inventory line references a printing missing from the backup")
    if any(profile.oracle_id not in oracle_ids for profile in backup.mechanic_profiles):
        raise HTTPException(400, detail="A mechanic profile references a card missing from the backup")
    if any(embedding.oracle_id not in oracle_ids for embedding in backup.embeddings):
        raise HTTPException(400, detail="An embedding references a card missing from the backup")
    if any(preference.oracle_id not in oracle_ids for preference in backup.card_preferences):
        raise HTTPException(400, detail="A preference references a card missing from the backup")
    _validate_grabbed_cards_against_backup(db, backup)

    try:
        for source in backup.oracle_cards:
            target = db.get(OracleCard, source.oracle_id)
            if target is None:
                target = OracleCard(oracle_id=source.oracle_id, name=source.name)
                db.add(target)
            for field in (
                "name", "type_line", "oracle_text", "mana_cost", "cmc", "colors",
                "color_identity", "legalities_json", "keywords", "synergy_tags",
                "tagged_at", "updated_at",
            ):
                setattr(target, field, getattr(source, field))
        db.flush()

        for source in backup.printings:
            target = db.get(CardPrinting, source.scryfall_id)
            if target is None:
                target = CardPrinting(
                    scryfall_id=source.scryfall_id,
                    oracle_id=source.oracle_id,
                )
                db.add(target)
            for field in (
                "oracle_id", "set_code", "collector_number", "rarity", "language",
                "image_uri_normal", "scryfall_json", "updated_at",
            ):
                setattr(target, field, getattr(source, field))
        db.flush()

        # A collection backup is a snapshot. Replacing the holdings makes an
        # import repeat-safe while leaving decks and their allocations alone.
        db.query(InventoryLine).delete(synchronize_session=False)
        for source in backup.inventory_lines:
            db.add(InventoryLine(**source.model_dump()))

        if oracle_ids:
            db.query(MechanicProfileRecord).filter(
                MechanicProfileRecord.oracle_id.in_(oracle_ids)
            ).delete(synchronize_session=False)
            db.query(OracleEmbeddingRecord).filter(
                OracleEmbeddingRecord.oracle_id.in_(oracle_ids)
            ).delete(synchronize_session=False)
            db.query(RecommendationCardPreference).filter(
                RecommendationCardPreference.oracle_id.in_(oracle_ids)
            ).delete(synchronize_session=False)

        for source in backup.mechanic_profiles:
            db.add(MechanicProfileRecord(**source.model_dump()))
        for source in backup.embeddings:
            try:
                vector = base64.b64decode(source.vector_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(
                    400, detail=f"Invalid embedding data for Oracle card {source.oracle_id}"
                ) from exc
            if len(vector) != source.dimensions * 4:
                raise HTTPException(
                    400,
                    detail=f"Embedding dimensions do not match its data for {source.oracle_id}",
                )
            values = source.model_dump(exclude={"vector_base64"})
            db.add(OracleEmbeddingRecord(**values, vector=vector))
        for source in backup.card_preferences:
            db.add(RecommendationCardPreference(**source.model_dump()))

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return CollectionImportResult(
        physical_cards=sum(line.quantity for line in backup.inventory_lines),
        unique_cards=len(oracle_ids),
        inventory_lines=len(backup.inventory_lines),
        mechanic_profiles=len(backup.mechanic_profiles),
        embeddings=len(backup.embeddings),
        card_preferences=len(backup.card_preferences),
    )
