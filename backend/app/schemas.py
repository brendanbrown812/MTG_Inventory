from datetime import datetime
from typing import Any, Literal

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
    set_code: str | None = None
    collector_number: str | None = None
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


class InventoryLineQuantityUpdate(BaseModel):
    quantity: int = Field(ge=1, le=999_999)


class InventoryCardAdd(BaseModel):
    scryfall_id: str = Field(min_length=36, max_length=36)
    quantity: int = Field(default=1, ge=1, le=999_999)
    foil: bool = False
    language: str = Field(default="en", min_length=2, max_length=10)


class CollectionOracleCardBackup(BaseModel):
    oracle_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=500)
    type_line: str | None = None
    oracle_text: str | None = None
    mana_cost: str | None = None
    cmc: float = 0
    colors: str = ""
    color_identity: str = ""
    legalities_json: str | None = None
    keywords: str | None = None
    synergy_tags: str | None = None
    tagged_at: datetime | None = None
    updated_at: datetime


class CollectionPrintingBackup(BaseModel):
    scryfall_id: str = Field(min_length=36, max_length=36)
    oracle_id: str = Field(min_length=36, max_length=36)
    set_code: str | None = None
    collector_number: str | None = None
    rarity: str | None = None
    language: str | None = None
    image_uri_normal: str | None = None
    scryfall_json: str | None = None
    updated_at: datetime


class CollectionInventoryLineBackup(BaseModel):
    scryfall_id: str = Field(min_length=36, max_length=36)
    quantity: int = Field(ge=1, le=999_999)
    foil: bool = False
    misprint: bool = False
    altered: bool = False
    condition: str | None = None
    language: str | None = None
    set_code: str | None = None
    collector_number: str | None = None
    purchase_price: float | None = None
    purchase_currency: str | None = None
    manabox_id: str | None = None


class CollectionMechanicProfileBackup(BaseModel):
    oracle_id: str = Field(min_length=36, max_length=36)
    schema_version: str
    taxonomy_version: str
    profile_json: str
    provider: str
    model: str
    confidence: float
    is_current: bool
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    created_at: datetime


class CollectionEmbeddingBackup(BaseModel):
    oracle_id: str = Field(min_length=36, max_length=36)
    provider: str
    model: str
    index_version: str
    dimensions: int = Field(ge=1)
    source_hash: str
    vector_base64: str
    is_current: bool
    input_tokens: int = Field(ge=0)
    created_at: datetime


class CollectionCardPreferenceBackup(BaseModel):
    oracle_id: str = Field(min_length=36, max_length=36)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    updated_at: datetime


class CollectionBackup(BaseModel):
    format: Literal["spellbinder.collection"]
    version: Literal[1]
    exported_at: datetime
    oracle_cards: list[CollectionOracleCardBackup] = Field(max_length=100_000)
    printings: list[CollectionPrintingBackup] = Field(max_length=100_000)
    inventory_lines: list[CollectionInventoryLineBackup] = Field(max_length=250_000)
    mechanic_profiles: list[CollectionMechanicProfileBackup] = Field(max_length=500_000)
    embeddings: list[CollectionEmbeddingBackup] = Field(max_length=500_000)
    card_preferences: list[CollectionCardPreferenceBackup] = Field(max_length=100_000)


class CollectionImportResult(BaseModel):
    physical_cards: int
    unique_cards: int
    inventory_lines: int
    mechanic_profiles: int
    embeddings: int
    card_preferences: int


class DeckBackupMetadata(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    format: str = Field(min_length=1, max_length=40)
    status: str = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=50_000)
    commander_scryfall_id: str | None = Field(default=None, min_length=36, max_length=36)
    commander_oracle_id: str | None = Field(default=None, min_length=36, max_length=36)


class DeckBackupAllocation(BaseModel):
    scryfall_id: str | None = Field(default=None, min_length=36, max_length=36)
    status: Literal["pending", "grabbed", "proxy"]
    quantity: int = Field(ge=1, le=999)
    foil: bool | None = None


class DeckBackupCard(BaseModel):
    scryfall_id: str = Field(min_length=36, max_length=36)
    oracle_id: str = Field(min_length=36, max_length=36)
    quantity: int = Field(ge=1, le=999)
    grabbed_quantity: int = Field(ge=0, le=999)
    proxy_quantity: int = Field(ge=0, le=999)
    is_commander: bool = False
    is_sideboard: bool = False
    allocations: list[DeckBackupAllocation] = Field(min_length=1, max_length=1_000)


class DeckBackup(BaseModel):
    format: Literal["spellbinder.deck"]
    version: Literal[1]
    exported_at: datetime
    deck: DeckBackupMetadata
    cards: list[DeckBackupCard] = Field(max_length=1_000)
    oracle_cards: list[CollectionOracleCardBackup] = Field(max_length=10_000)
    printings: list[CollectionPrintingBackup] = Field(max_length=25_000)
    mechanic_profiles: list[CollectionMechanicProfileBackup] = Field(max_length=50_000)
    embeddings: list[CollectionEmbeddingBackup] = Field(max_length=50_000)
    card_preferences: list[CollectionCardPreferenceBackup] = Field(max_length=10_000)


class DeckBackupPreview(BaseModel):
    name: str
    format: str
    status: str
    total_cards: int
    grabbed_cards: int
    proxy_cards: int
    sideboard_cards: int


class InventoryPrintingOut(BaseModel):
    scryfall_id: str
    set_code: str | None
    collector_number: str | None
    rarity: str | None
    language: str | None
    image_uri_normal: str | None
    total_quantity: int
    foil_quantity: int
    nonfoil_quantity: int
    card: CardOut
    lines: list[InventoryLineOut]


class InventoryOracleGroupOut(BaseModel):
    oracle_id: str
    total_quantity: int
    printing_count: int
    inventory_line_count: int
    card: CardOut
    printings: list[InventoryPrintingOut]

class DeckCardIn(BaseModel):
    scryfall_id: str = Field(min_length=36, max_length=36)
    quantity: int = Field(default=1, ge=1, le=999)
    is_commander: bool = False
    is_sideboard: bool = False


class DeckCardAssemblyUpdate(BaseModel):
    grabbed_quantity: int = Field(default=0, ge=0, le=999)
    proxy_quantity: int = Field(default=0, ge=0, le=999)


class DeckAssemblyEntryUpdate(DeckCardAssemblyUpdate):
    deck_card_id: int = Field(ge=1)


class DeckAssemblyBatchUpdate(BaseModel):
    cards: list[DeckAssemblyEntryUpdate] = Field(min_length=1, max_length=1_000)


class DeckCardAllocationIn(BaseModel):
    status: Literal["pending", "grabbed", "proxy"]
    quantity: int = Field(ge=1, le=999)
    scryfall_id: str | None = Field(default=None, min_length=36, max_length=36)
    foil: bool | None = None


class DeckCardAllocationReplace(BaseModel):
    allocations: list[DeckCardAllocationIn] = Field(min_length=1, max_length=1_000)


class DeckDraftCopyIn(BaseModel):
    card_scryfall_id: str = Field(min_length=36, max_length=36)
    printing_scryfall_id: str | None = Field(default=None, min_length=36, max_length=36)
    status: Literal["pending", "grabbed", "proxy"] = "pending"
    foil: bool | None = None
    is_commander: bool = False
    is_sideboard: bool = False
    add_to_collection: bool = False
    collection_addition_id: str | None = Field(default=None, min_length=36, max_length=36)


class DeckDraftSave(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    format: str = Field(min_length=1, max_length=40)
    status: str = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=50_000)
    cards: list[DeckDraftCopyIn] = Field(default_factory=list, max_length=1_000)


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
    commander_name: str | None = None

class DeckDetailOut(DeckOut):
    cards: list["DeckCardOut"] = Field(default_factory=list)


class DeckCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scryfall_id: str
    quantity: int
    grabbed_quantity: int
    proxy_quantity: int
    is_commander: bool
    is_sideboard: bool
    card: CardOut | None
    allocations: list["DeckCardAllocationOut"] = Field(default_factory=list)


class DeckCardAllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: Literal["pending", "grabbed", "proxy"]
    quantity: int
    scryfall_id: str | None
    foil: bool | None
    printing: CardOut | None

DeckDetailOut.model_rebuild()
DeckCardOut.model_rebuild()


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


class PrintingOptionOut(BaseModel):
    scryfall_id: str
    name: str
    set_name: str
    set_code: str | None = None
    collector_number: str | None = None
    released_at: str | None = None
    language: str | None = None
    image_uri_normal: str | None = None
    foil: bool = False
    nonfoil: bool = False


class InventoryPrintingChange(BaseModel):
    target_scryfall_id: str = Field(min_length=36, max_length=36)
    quantity: int | None = Field(default=None, ge=1, le=999_999)


class InventoryPrintingChangeOut(BaseModel):
    changed_lines: int
    moved_quantity: int
    source_scryfall_id: str
    target_scryfall_id: str


class CardResolveMatch(CardOut):
    pass


class CardResolveOut(BaseModel):
    matches: list[CardResolveMatch]


class DeckCsvRowError(BaseModel):
    row_index: int
    error: str


class DeckCsvImportOut(BaseModel):
    deck: DeckDetailOut
    row_errors: list[DeckCsvRowError] = Field(default_factory=list)


DeckCsvImportOut.model_rebuild()
