from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.embeddings.base import (
    SEMANTIC_INDEX_VERSION,
    EmbeddingProvider,
    card_embedding_text,
    content_hash,
    decode_vector,
    encode_vector,
    query_embedding_text,
)
from app.embeddings.registry import build_embedding_provider, embedding_provider_is_configured
from app.logging_setup import get_logger
from app.mechanics.profile import PROFILE_SCHEMA_VERSION, TAXONOMY_VERSION
from app.models import (
    MechanicProfileRecord,
    OracleCard,
    OracleEmbeddingRecord,
    SemanticQueryEmbedding,
)


_log = get_logger(".semantic_index")
EMBEDDING_PRICE_PER_MILLION_TOKENS = 0.02
SEED_EMBEDDING_TOKENS_PER_CARD = 180


@dataclass(frozen=True)
class PendingEmbedding:
    card: OracleCard
    text: str
    source_hash: str


def _configuration_filter(query):
    return query.filter(
        OracleEmbeddingRecord.provider == settings.embedding_provider,
        OracleEmbeddingRecord.model == settings.embedding_model,
        OracleEmbeddingRecord.index_version == SEMANTIC_INDEX_VERSION,
        OracleEmbeddingRecord.dimensions == settings.embedding_dimensions,
        OracleEmbeddingRecord.is_current.is_(True),
    )


def _cards_with_profiles(db: Session) -> list[tuple[OracleCard, MechanicProfileRecord | None]]:
    return (
        db.query(OracleCard, MechanicProfileRecord)
        .outerjoin(
            MechanicProfileRecord,
            (MechanicProfileRecord.oracle_id == OracleCard.oracle_id)
            & MechanicProfileRecord.is_current.is_(True)
            & (MechanicProfileRecord.schema_version == PROFILE_SCHEMA_VERSION)
            & (MechanicProfileRecord.taxonomy_version == TAXONOMY_VERSION),
        )
        .order_by(OracleCard.oracle_id)
        .all()
    )


def pending_card_embeddings(db: Session, limit: int | None = None) -> list[PendingEmbedding]:
    current = {
        record.oracle_id: record.source_hash
        for record in _configuration_filter(db.query(OracleEmbeddingRecord)).all()
    }
    pending: list[PendingEmbedding] = []
    for card, profile in _cards_with_profiles(db):
        text = card_embedding_text(card, profile)
        source_hash = content_hash(text)
        if current.get(card.oracle_id) == source_hash:
            continue
        pending.append(PendingEmbedding(card, text, source_hash))
        if limit is not None and len(pending) >= limit:
            break
    return pending


def persist_card_embedding_batch(
    db: Session,
    provider: EmbeddingProvider,
    pending: list[PendingEmbedding],
) -> int:
    if not pending:
        return 0
    batch = provider.embed([item.text for item in pending])
    if len(batch.vectors) != len(pending):
        raise RuntimeError(
            f"Embedding provider returned {len(batch.vectors)} vectors for {len(pending)} cards"
        )
    if any(len(vector) != provider.dimensions for vector in batch.vectors):
        raise RuntimeError("Embedding provider returned an unexpected vector dimension")

    base_tokens, remainder = divmod(batch.input_tokens, len(pending))
    for index, (item, vector) in enumerate(zip(pending, batch.vectors)):
        db.query(OracleEmbeddingRecord).filter(
            OracleEmbeddingRecord.oracle_id == item.card.oracle_id,
            OracleEmbeddingRecord.is_current.is_(True),
        ).update({OracleEmbeddingRecord.is_current: False}, synchronize_session=False)
        existing = db.query(OracleEmbeddingRecord).filter(
            OracleEmbeddingRecord.oracle_id == item.card.oracle_id,
            OracleEmbeddingRecord.provider == provider.provider_name,
            OracleEmbeddingRecord.model == provider.model_name,
            OracleEmbeddingRecord.index_version == SEMANTIC_INDEX_VERSION,
            OracleEmbeddingRecord.dimensions == provider.dimensions,
            OracleEmbeddingRecord.source_hash == item.source_hash,
        ).first()
        values = {
            "vector": encode_vector(vector),
            "is_current": True,
            "input_tokens": base_tokens + (1 if index < remainder else 0),
        }
        if existing is not None:
            for key, value in values.items():
                setattr(existing, key, value)
        else:
            db.add(OracleEmbeddingRecord(
                oracle_id=item.card.oracle_id,
                provider=provider.provider_name,
                model=provider.model_name,
                index_version=SEMANTIC_INDEX_VERSION,
                dimensions=provider.dimensions,
                source_hash=item.source_hash,
                **values,
            ))
    return batch.input_tokens


def semantic_index_status(db: Session) -> dict:
    total = db.query(OracleCard).count()
    pending = pending_card_embeddings(db)
    current = total - len(pending)
    token_stats = _configuration_filter(db.query(OracleEmbeddingRecord)).all()
    indexed_tokens = sum(record.input_tokens for record in token_stats)
    avg_tokens = indexed_tokens / len(token_stats) if token_stats else None
    estimated_tokens = len(pending) * (
        avg_tokens if avg_tokens is not None else SEED_EMBEDDING_TOKENS_PER_CARD
    )
    return {
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "embedding_index_version": SEMANTIC_INDEX_VERSION,
        "embedding_provider_configured": embedding_provider_is_configured(),
        "embedded_cards": current,
        "unembedded_cards": len(pending),
        "avg_embedding_tokens_per_card": avg_tokens,
        "estimated_cost_all_unembedded": round(
            estimated_tokens * EMBEDDING_PRICE_PER_MILLION_TOKENS / 1_000_000,
            6,
        ),
    }


def current_card_vectors(
    db: Session,
    oracle_ids: list[str],
) -> dict[str, tuple[float, ...]]:
    if not oracle_ids:
        return {}
    records = _configuration_filter(
        db.query(OracleEmbeddingRecord).filter(
            OracleEmbeddingRecord.oracle_id.in_(oracle_ids)
        )
    ).all()
    rows_by_id = {card.oracle_id: (card, profile) for card, profile in _cards_with_profiles(db)}
    result: dict[str, tuple[float, ...]] = {}
    for record in records:
        pair = rows_by_id.get(record.oracle_id)
        if pair is None:
            continue
        card, profile = pair
        if record.source_hash != content_hash(card_embedding_text(card, profile)):
            continue
        try:
            result[record.oracle_id] = decode_vector(record.vector, record.dimensions)
        except ValueError:
            _log.warning("Ignoring corrupt embedding oracle_id=%s", record.oracle_id)
    return result


def get_or_create_query_vector(
    db: Session,
    query_text: str,
    *,
    provider: EmbeddingProvider | None = None,
    allow_provider_request: bool = True,
) -> tuple[float, ...] | None:
    text = query_embedding_text(query_text)
    source_hash = content_hash(text)
    cached = db.query(SemanticQueryEmbedding).filter(
        SemanticQueryEmbedding.provider == settings.embedding_provider,
        SemanticQueryEmbedding.model == settings.embedding_model,
        SemanticQueryEmbedding.index_version == SEMANTIC_INDEX_VERSION,
        SemanticQueryEmbedding.dimensions == settings.embedding_dimensions,
        SemanticQueryEmbedding.source_hash == source_hash,
    ).first()
    if cached is not None:
        try:
            return decode_vector(cached.vector, cached.dimensions)
        except ValueError:
            if allow_provider_request:
                db.delete(cached)
                db.commit()
            else:
                return None

    if not allow_provider_request:
        return None
    if provider is None:
        if not embedding_provider_is_configured():
            return None
        provider = build_embedding_provider()
    batch = provider.embed([text])
    if len(batch.vectors) != 1 or len(batch.vectors[0]) != provider.dimensions:
        raise RuntimeError("Embedding provider returned an invalid query vector")
    vector = batch.vectors[0]
    db.add(SemanticQueryEmbedding(
        provider=provider.provider_name,
        model=provider.model_name,
        index_version=SEMANTIC_INDEX_VERSION,
        dimensions=provider.dimensions,
        source_hash=source_hash,
        vector=encode_vector(vector),
        input_tokens=batch.input_tokens,
    ))
    db.commit()
    return vector
