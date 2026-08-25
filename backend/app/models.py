from datetime import UTC, datetime

from sqlalchemy import LargeBinary, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    """Naive UTC for compatibility with the existing SQLite columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class OracleCard(Base):
    """Printing-independent card identity and game mechanics."""

    __tablename__ = "oracle_cards"

    oracle_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    type_line: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oracle_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    mana_cost: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cmc: Mapped[float] = mapped_column(Float, default=0)
    colors: Mapped[str] = mapped_column(String(20), default="")
    color_identity: Mapped[str] = mapped_column(String(20), default="")
    legalities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    synergy_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    tagged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    printings: Mapped[list["CardPrinting"]] = relationship(back_populates="oracle")
    mechanic_profiles: Mapped[list["MechanicProfileRecord"]] = relationship(
        back_populates="oracle", cascade="all, delete-orphan"
    )
    semantic_embeddings: Mapped[list["OracleEmbeddingRecord"]] = relationship(
        back_populates="oracle", cascade="all, delete-orphan"
    )


class CardPrinting(Base):
    """A physical/digital printing of an Oracle card."""

    __tablename__ = "card_printings"

    scryfall_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    oracle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("oracle_cards.oracle_id"), index=True
    )
    set_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    collector_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rarity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_uri_normal: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    scryfall_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    oracle: Mapped[OracleCard] = relationship(back_populates="printings")

    # Compatibility properties keep current API/service behavior while mechanics
    # live only on OracleCard.
    @property
    def name(self) -> str:
        return self.oracle.name

    @property
    def type_line(self) -> str | None:
        return self.oracle.type_line

    @property
    def oracle_text(self) -> str | None:
        return self.oracle.oracle_text

    @property
    def mana_cost(self) -> str | None:
        return self.oracle.mana_cost

    @property
    def cmc(self) -> float:
        return self.oracle.cmc

    @property
    def colors(self) -> str:
        return self.oracle.colors

    @property
    def color_identity(self) -> str:
        return self.oracle.color_identity

    @property
    def legalities_json(self) -> str | None:
        return self.oracle.legalities_json

    @property
    def keywords(self) -> str | None:
        return self.oracle.keywords

    @property
    def synergy_tags(self) -> str | None:
        return self.oracle.synergy_tags

    @property
    def tagged_at(self) -> datetime | None:
        return self.oracle.tagged_at


class InventoryLine(Base):
    __tablename__ = "inventory_lines"
    __table_args__ = (
        UniqueConstraint("scryfall_id", "foil", "condition", "language", name="uq_inv_line"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scryfall_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("card_printings.scryfall_id"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    foil: Mapped[bool] = mapped_column(Boolean, default=False)
    misprint: Mapped[bool] = mapped_column(Boolean, default=False)
    altered: Mapped[bool] = mapped_column(Boolean, default=False)
    condition: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    set_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    collector_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchase_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    manabox_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    card: Mapped[CardPrinting] = relationship()


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(40), default="commander")
    status: Mapped[str] = mapped_column(String(20), default="building")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    commander_scryfall_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    commander_oracle_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("oracle_cards.oracle_id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    cards: Mapped[list["DeckCard"]] = relationship(back_populates="deck", cascade="all, delete-orphan")


class DeckCard(Base):
    __tablename__ = "deck_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deck_id: Mapped[int] = mapped_column(Integer, ForeignKey("decks.id"), index=True)
    scryfall_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("card_printings.scryfall_id"), index=True
    )
    oracle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("oracle_cards.oracle_id"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    is_commander: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sideboard: Mapped[bool] = mapped_column(Boolean, default=False)

    deck: Mapped[Deck] = relationship(back_populates="cards")
    card: Mapped[CardPrinting] = relationship()
    oracle_card: Mapped[OracleCard] = relationship()


class EnrichmentStats(Base):
    """Logs structured enrichment usage; keeps the legacy table name in place."""

    __tablename__ = "tagging_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cards_processed: Mapped[int] = mapped_column(Integer)
    called_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MechanicProfileRecord(Base):
    """Versioned, provider-attributed structured enrichment for an Oracle card."""

    __tablename__ = "mechanic_profiles"
    __table_args__ = (
        Index("ix_mechanic_profiles_current", "oracle_id", "is_current"),
        Index("ix_mechanic_profiles_versions", "schema_version", "taxonomy_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oracle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("oracle_cards.oracle_id"), index=True
    )
    schema_version: Mapped[str] = mapped_column(String(20))
    taxonomy_version: Mapped[str] = mapped_column(String(20))
    profile_json: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    oracle: Mapped[OracleCard] = relationship(back_populates="mechanic_profiles")


class OracleEmbeddingRecord(Base):
    """Compact, versioned vector for an Oracle card's current mechanics text."""

    __tablename__ = "oracle_embeddings"
    __table_args__ = (
        Index("ix_oracle_embeddings_current", "oracle_id", "is_current"),
        Index(
            "ix_oracle_embeddings_configuration",
            "provider", "model", "index_version", "dimensions", "is_current",
        ),
        UniqueConstraint(
            "oracle_id", "provider", "model", "index_version", "dimensions", "source_hash",
            name="uq_oracle_embedding_content",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    oracle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("oracle_cards.oracle_id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    index_version: Mapped[str] = mapped_column(String(20))
    dimensions: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    oracle: Mapped[OracleCard] = relationship(back_populates="semantic_embeddings")


class SemanticQueryEmbedding(Base):
    """Persistent cache that avoids rebilling identical retrieval requests."""

    __tablename__ = "semantic_query_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "provider", "model", "index_version", "dimensions", "source_hash",
            name="uq_semantic_query_embedding",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    index_version: Mapped[str] = mapped_column(String(20))
    dimensions: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class OpenAIUsageRecord(Base):
    """Local reservation and actual usage ledger for paid OpenAI requests."""

    __tablename__ = "openai_usage_records"
    __table_args__ = (
        Index("ix_openai_usage_month", "created_at", "status"),
        Index("ix_openai_usage_workflow", "workflow", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    pricing_version: Mapped[str] = mapped_column(String(20))
    estimated_max_cost_usd: Mapped[float] = mapped_column(Float)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    response_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RecommendationRun(Base):
    """Immutable provenance for a bounded recommendation and optimizer result."""

    __tablename__ = "recommendation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="build")
    query_text: Mapped[str] = mapped_column(Text)
    requested_commander: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    proposal_json: Mapped[str] = mapped_column(Text)
    optimizer_json: Mapped[str] = mapped_column(Text)
    candidate_pool_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RecommendationFeedback(Base):
    __tablename__ = "recommendation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recommendation_runs.id"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(20))
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_entries_json: Mapped[str] = mapped_column(Text)
    added_or_increased_json: Mapped[str] = mapped_column(Text)
    removed_or_decreased_json: Mapped[str] = mapped_column(Text)
    saved_deck_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("decks.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RecommendationCardPreference(Base):
    """Explicit feedback signal used as a transparent retrieval component."""

    __tablename__ = "recommendation_card_preferences"

    oracle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("oracle_cards.oracle_id"), primary_key=True
    )
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
