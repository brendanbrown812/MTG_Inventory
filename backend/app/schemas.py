from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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

class InventoryLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scryfall_id: str
    quantity: int
    foil: bool
    condition: str | None
    language: str | None
    set_code: str | None
    collector_number: str | None
    card: CardOut | None

class DeckCardIn(BaseModel):
    scryfall_id: str = Field(min_length=36, max_length=36)
    quantity: int = Field(default=1, ge=1, le=999)
    is_commander: bool = False
    is_sideboard: bool = False


class DeckCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    format: str = Field(default="commander", min_length=1, max_length=40)
    status: str = Field(default="building", min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=50_000)
    commander_scryfall_id: str | None = Field(default=None, min_length=36, max_length=36)
    cards: list[DeckCardIn] = Field(default_factory=list, max_length=1_000)


class DeckUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    format: str | None = Field(default=None, min_length=1, max_length=40)
    status: str | None = Field(default=None, min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=50_000)
    commander_scryfall_id: str | None = Field(default=None, min_length=36, max_length=36)


class DeckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    format: str
    status: str
    notes: str | None
    commander_scryfall_id: str | None

class DeckDetailOut(DeckOut):
    cards: list["DeckCardOut"] = Field(default_factory=list)


class DeckCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scryfall_id: str
    quantity: int
    is_commander: bool
    is_sideboard: bool
    card: CardOut | None

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
