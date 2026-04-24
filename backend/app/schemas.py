from typing import Any

from pydantic import BaseModel, Field


class CardOut(BaseModel):
    scryfall_id: str
    oracle_id: str
    name: str
    type_line: str | None
    mana_cost: str | None
    cmc: float
    colors: str
    color_identity: str
    rarity: str | None
    image_uri_normal: str | None

    class Config:
        from_attributes = True


class InventoryLineOut(BaseModel):
    id: int
    scryfall_id: str
    quantity: int
    foil: bool
    condition: str | None
    language: str | None
    set_code: str | None
    collector_number: str | None
    card: CardOut | None

    class Config:
        from_attributes = True


class DeckCardIn(BaseModel):
    scryfall_id: str
    quantity: int = 1
    is_commander: bool = False
    is_sideboard: bool = False


class DeckCreate(BaseModel):
    name: str
    format: str = "commander"
    status: str = "building"
    notes: str | None = None
    commander_scryfall_id: str | None = None
    cards: list[DeckCardIn] = Field(default_factory=list)


class DeckUpdate(BaseModel):
    name: str | None = None
    format: str | None = None
    status: str | None = None
    notes: str | None = None
    commander_scryfall_id: str | None = None


class DeckOut(BaseModel):
    id: int
    name: str
    format: str
    status: str
    notes: str | None
    commander_scryfall_id: str | None

    class Config:
        from_attributes = True


class DeckDetailOut(DeckOut):
    cards: list["DeckCardOut"] = Field(default_factory=list)


class DeckCardOut(BaseModel):
    id: int
    scryfall_id: str
    quantity: int
    is_commander: bool
    is_sideboard: bool
    card: CardOut | None

    class Config:
        from_attributes = True


DeckDetailOut.model_rebuild()


class ImportRowResult(BaseModel):
    row_index: int
    scryfall_id: str | None
    name: str | None
    ok: bool
    error: str | None = None
    matches: list[dict[str, Any]] = Field(default_factory=list)
    image_uri_normal: str | None = None


class ImportResult(BaseModel):
    added_quantity: int
    rows: list[ImportRowResult]


class ClearInventoryResult(BaseModel):
    deleted: int


class CardResolveMatch(BaseModel):
    scryfall_id: str
    name: str
    type_line: str | None = None
    image_uri_normal: str | None = None


class CardResolveOut(BaseModel):
    matches: list[CardResolveMatch]


class DeckCsvRowError(BaseModel):
    row_index: int
    error: str


class DeckCsvImportOut(BaseModel):
    deck: DeckDetailOut
    row_errors: list[DeckCsvRowError] = Field(default_factory=list)


DeckCsvImportOut.model_rebuild()
