from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload

from app.models import (
    CardPrinting,
    Deck,
    DeckCard,
    DeckCardAllocation,
    MechanicProfileRecord,
    OracleCard,
    OracleEmbeddingRecord,
    RecommendationCardPreference,
)
from app.schemas import DeckBackup


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def build_deck_backup(db: Session, deck_id: int) -> DeckBackup:
    deck = (
        db.query(Deck)
        .options(joinedload(Deck.cards).joinedload(DeckCard.allocations))
        .filter(Deck.id == deck_id)
        .first()
    )
    if deck is None:
        raise HTTPException(404, detail="Deck not found")

    oracle_ids = sorted({card.oracle_id for card in deck.cards})
    printing_ids = {
        card.scryfall_id for card in deck.cards
    } | {
        allocation.scryfall_id
        for card in deck.cards
        for allocation in card.allocations
        if allocation.scryfall_id
    }
    if deck.commander_scryfall_id:
        printing_ids.add(deck.commander_scryfall_id)

    oracle_cards = (
        db.query(OracleCard)
        .filter(OracleCard.oracle_id.in_(oracle_ids))
        .order_by(OracleCard.oracle_id)
        .all()
        if oracle_ids else []
    )
    printings = (
        db.query(CardPrinting)
        .filter(CardPrinting.scryfall_id.in_(printing_ids))
        .order_by(CardPrinting.scryfall_id)
        .all()
        if printing_ids else []
    )
    profiles = (
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

    backup = DeckBackup.model_validate({
        "format": "spellbinder.deck",
        "version": 1,
        "exported_at": _utcnow(),
        "deck": {
            "name": deck.name,
            "format": deck.format,
            "status": deck.status,
            "notes": deck.notes,
            "commander_scryfall_id": deck.commander_scryfall_id,
            "commander_oracle_id": deck.commander_oracle_id,
        },
        "cards": [{
            "scryfall_id": card.scryfall_id,
            "oracle_id": card.oracle_id,
            "quantity": card.quantity,
            "grabbed_quantity": card.grabbed_quantity,
            "proxy_quantity": card.proxy_quantity,
            "is_commander": card.is_commander,
            "is_sideboard": card.is_sideboard,
            "allocations": [{
                "scryfall_id": allocation.scryfall_id,
                "status": allocation.status,
                "quantity": allocation.quantity,
                "foil": allocation.foil,
            } for allocation in sorted(card.allocations, key=lambda row: row.id)],
        } for card in sorted(deck.cards, key=lambda row: row.id)],
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
        } for profile in profiles],
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
    _validate_deck_backup(backup)
    return backup


def parse_deck_backup(raw_json: bytes) -> DeckBackup:
    try:
        return DeckBackup.model_validate_json(raw_json)
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(value) for value in first.get("loc", ()))
        raise HTTPException(
            400,
            detail=(
                f"Invalid Spellbinder deck backup at {location}: "
                f"{first.get('msg', 'invalid value')}"
            ),
        ) from exc


def _validate_deck_backup(backup: DeckBackup) -> None:
    oracle_ids = {card.oracle_id for card in backup.oracle_cards}
    printing_oracles = {
        printing.scryfall_id: printing.oracle_id for printing in backup.printings
    }
    if any(oracle_id not in oracle_ids for oracle_id in printing_oracles.values()):
        raise HTTPException(400, detail="A deck printing references missing Oracle data")
    commanders = [card for card in backup.cards if card.is_commander]
    if len(commanders) > 1:
        raise HTTPException(400, detail="A deck backup can contain only one commander")

    for card in backup.cards:
        if card.oracle_id not in oracle_ids:
            raise HTTPException(400, detail="A deck card references missing Oracle data")
        if printing_oracles.get(card.scryfall_id) != card.oracle_id:
            raise HTTPException(400, detail="A deck card references an incompatible printing")
        if card.is_commander and card.is_sideboard:
            raise HTTPException(400, detail="A sideboard card cannot be the commander")
        if sum(row.quantity for row in card.allocations) != card.quantity:
            raise HTTPException(400, detail="Deck allocation quantities do not match the card quantity")
        grabbed = sum(row.quantity for row in card.allocations if row.status == "grabbed")
        proxies = sum(row.quantity for row in card.allocations if row.status == "proxy")
        if grabbed != card.grabbed_quantity or proxies != card.proxy_quantity:
            raise HTTPException(400, detail="Deck allocation statuses do not match their totals")
        for allocation in card.allocations:
            if allocation.scryfall_id is None:
                if allocation.foil is not None:
                    raise HTTPException(400, detail="Any-printing allocations cannot specify foil")
            elif printing_oracles.get(allocation.scryfall_id) != card.oracle_id:
                raise HTTPException(400, detail="A deck allocation uses an incompatible printing")

    commander = commanders[0] if commanders else None
    if commander is None:
        if backup.deck.commander_oracle_id or backup.deck.commander_scryfall_id:
            raise HTTPException(400, detail="Commander pointers exist without a commander card")
    else:
        if backup.deck.commander_oracle_id != commander.oracle_id:
            raise HTTPException(400, detail="Commander Oracle data does not match the selected card")
        if printing_oracles.get(backup.deck.commander_scryfall_id) != commander.oracle_id:
            raise HTTPException(400, detail="Commander printing does not match the selected card")


def import_deck_backup(
    db: Session,
    backup: DeckBackup,
    *,
    name: str,
    preserve_positions: bool,
) -> int:
    _validate_deck_backup(backup)
    oracle_ids = {card.oracle_id for card in backup.oracle_cards}
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
                target = CardPrinting(scryfall_id=source.scryfall_id, oracle_id=source.oracle_id)
                db.add(target)
            for field in (
                "oracle_id", "set_code", "collector_number", "rarity", "language",
                "image_uri_normal", "scryfall_json", "updated_at",
            ):
                setattr(target, field, getattr(source, field))
        db.flush()

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
                    400, detail=f"Embedding dimensions do not match its data for {source.oracle_id}"
                )
            values = source.model_dump(exclude={"vector_base64"})
            db.add(OracleEmbeddingRecord(**values, vector=vector))
        for source in backup.card_preferences:
            db.add(RecommendationCardPreference(**source.model_dump()))

        deck_values = backup.deck.model_dump()
        deck_values["name"] = name
        deck = Deck(**deck_values)
        db.add(deck)
        db.flush()
        for source in backup.cards:
            card = DeckCard(
                deck_id=deck.id,
                scryfall_id=source.scryfall_id,
                oracle_id=source.oracle_id,
                quantity=source.quantity,
                grabbed_quantity=source.grabbed_quantity if preserve_positions else 0,
                proxy_quantity=source.proxy_quantity if preserve_positions else 0,
                is_commander=source.is_commander,
                is_sideboard=source.is_sideboard,
            )
            db.add(card)
            db.flush()
            for allocation in source.allocations:
                allocation_values = allocation.model_dump()
                if not preserve_positions:
                    allocation_values["status"] = "pending"
                db.add(DeckCardAllocation(
                    deck_card_id=card.id,
                    **allocation_values,
                ))
        db.commit()
        return deck.id
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
