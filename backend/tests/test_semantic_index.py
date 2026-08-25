from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import settings
from app.database import SessionLocal
from app.embeddings.base import (
    SEMANTIC_INDEX_VERSION,
    EmbeddingBatch,
    card_embedding_text,
    content_hash,
    decode_vector,
    encode_vector,
    query_embedding_text,
)
from app.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.models import (
    CardPrinting,
    InventoryLine,
    OracleCard,
    OracleEmbeddingRecord,
    SemanticQueryEmbedding,
)
from app.services.candidate_retrieval import retrieve_owned_candidates
from app.services.semantic_index import (
    pending_card_embeddings,
    persist_card_embedding_batch,
    semantic_index_status,
)


class FakeEmbeddingProvider:
    provider_name = "openai"
    model_name = "text-embedding-3-small"
    dimensions = 3

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            vectors=tuple((1.0, float(index), 0.0) for index, _ in enumerate(texts)),
            input_tokens=10 * len(texts),
        )


def _add_owned(db, oracle_id: str, name: str, oracle_text: str) -> OracleCard:
    card = OracleCard(
        oracle_id=oracle_id,
        name=name,
        type_line="Creature",
        oracle_text=oracle_text,
        legalities_json=json.dumps({"commander": "legal"}),
        keywords="[]",
    )
    db.add(card)
    db.add(CardPrinting(scryfall_id=f"printing-{oracle_id}", oracle_id=oracle_id))
    db.add(InventoryLine(scryfall_id=f"printing-{oracle_id}", quantity=1))
    return card


def test_openai_provider_batches_inputs_preserves_order_and_usage() -> None:
    request: dict = {}

    class FakeEmbeddings:
        def create(self, **kwargs):
            request.update(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[0.0, 2.0, 0.0]),
                    SimpleNamespace(index=0, embedding=[3.0, 0.0, 0.0]),
                ],
                usage=SimpleNamespace(prompt_tokens=17, total_tokens=17),
            )

    provider = OpenAIEmbeddingProvider(
        "test-key",
        "text-embedding-3-small",
        3,
        client_factory=lambda **_: SimpleNamespace(embeddings=FakeEmbeddings()),
    )
    result = provider.embed(["first", "second"])

    assert request == {
        "model": "text-embedding-3-small",
        "input": ["first", "second"],
        "dimensions": 3,
        "encoding_format": "float",
    }
    assert result.vectors == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert result.input_tokens == 17


def test_index_is_content_addressed_persistent_and_stale_safe() -> None:
    with SessionLocal() as db:
        card = _add_owned(db, "oracle-indexed", "Hidden Engine", "Whenever this attacks, draw a card.")
        db.commit()

        pending = pending_card_embeddings(db)
        assert [item.card.oracle_id for item in pending] == ["oracle-indexed"]

        provider = FakeEmbeddingProvider()
        original_dimensions = settings.embedding_dimensions
        try:
            settings.embedding_dimensions = 3
            assert persist_card_embedding_batch(db, provider, pending) == 10
            db.commit()
            assert pending_card_embeddings(db) == []
            record = db.query(OracleEmbeddingRecord).one()
            assert decode_vector(record.vector, 3) == (1.0, 0.0, 0.0)
            assert record.input_tokens == 10

            card.oracle_text = "Whenever this attacks, create a Treasure token."
            db.commit()
            stale = pending_card_embeddings(db)
            assert len(stale) == 1
            assert stale[0].source_hash != record.source_hash
        finally:
            settings.embedding_dimensions = original_dimensions


def test_retrieval_uses_cached_embedding_with_transparent_provenance() -> None:
    original_dimensions = settings.embedding_dimensions
    try:
        settings.embedding_dimensions = 3
        with SessionLocal() as db:
            semantic_card = _add_owned(
                db, "oracle-semantic", "Unexpected Ally", "Creatures you control get +1/+1."
            )
            lexical_card = _add_owned(
                db, "oracle-lexical", "Graveyard Words", "Return a card from your graveyard."
            )
            db.flush()
            for card, vector in ((semantic_card, (1.0, 0.0, 0.0)), (lexical_card, (0.0, 1.0, 0.0))):
                text = card_embedding_text(card)
                db.add(OracleEmbeddingRecord(
                    oracle_id=card.oracle_id,
                    provider=settings.embedding_provider,
                    model=settings.embedding_model,
                    index_version=SEMANTIC_INDEX_VERSION,
                    dimensions=3,
                    source_hash=content_hash(text),
                    vector=encode_vector(vector),
                    is_current=True,
                ))
            query = "graveyard recursion"
            db.add(SemanticQueryEmbedding(
                provider=settings.embedding_provider,
                model=settings.embedding_model,
                index_version=SEMANTIC_INDEX_VERSION,
                dimensions=3,
                source_hash=content_hash(query_embedding_text(query)),
                vector=encode_vector((1.0, 0.0, 0.0)),
            ))
            db.commit()

            results = retrieve_owned_candidates(db, query)
            assert results[0]["name"] == "Unexpected Ally"
            provenance = results[0]["retrieval"]["semantic"]
            assert provenance["source"] == "openai_embedding"
            assert provenance["similarity"] == 1.0
            assert provenance["embedding_similarity"] == 1.0
            assert provenance["lexical_similarity"] < 0.1
            assert results[0]["retrieval"]["components"]["semantic"] == 25.0
            assert any(
                "OpenAI embedding similarity" in reason
                for reason in results[0]["retrieval"]["reasons"]
            )
    finally:
        settings.embedding_dimensions = original_dimensions


def test_status_and_endpoint_respect_paid_request_lock(client) -> None:
    with SessionLocal() as db:
        _add_owned(db, "oracle-status", "Status Card", "Draw a card.")
        db.commit()
        status = semantic_index_status(db)
        assert status["embedded_cards"] == 0
        assert status["unembedded_cards"] == 1
        assert status["embedding_provider_configured"] is False
        assert status["estimated_cost_all_unembedded"] > 0

    response = client.post("/api/enrichment/index-embeddings", json={"batch_size": 1})
    assert response.status_code == 400
    assert "OPENAI_REQUESTS_ENABLED" in response.json()["detail"]
