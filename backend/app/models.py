from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CardCache(Base):
    __tablename__ = "card_cache"

    scryfall_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    oracle_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(500))
    type_line: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oracle_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    mana_cost: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cmc: Mapped[float] = mapped_column(Float, default=0)
    colors: Mapped[str] = mapped_column(String(20), default="")  # WUBRG JSON-less: joined "W,U"
    color_identity: Mapped[str] = mapped_column(String(20), default="")
    rarity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_uri_normal: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    legalities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scryfall_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InventoryLine(Base):
    __tablename__ = "inventory_lines"
    __table_args__ = (UniqueConstraint("scryfall_id", "foil", "condition", "language", name="uq_inv_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scryfall_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_cache.scryfall_id"), index=True)
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

    card: Mapped["CardCache"] = relationship()


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(40), default="commander")  # commander, standard, etc.
    status: Mapped[str] = mapped_column(String(20), default="building")  # building, complete
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    commander_scryfall_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cards: Mapped[list["DeckCard"]] = relationship(back_populates="deck", cascade="all, delete-orphan")


class DeckCard(Base):
    __tablename__ = "deck_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deck_id: Mapped[int] = mapped_column(Integer, ForeignKey("decks.id"), index=True)
    scryfall_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_cache.scryfall_id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    is_commander: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sideboard: Mapped[bool] = mapped_column(Boolean, default=False)

    deck: Mapped["Deck"] = relationship(back_populates="cards")
    card: Mapped["CardCache"] = relationship()
