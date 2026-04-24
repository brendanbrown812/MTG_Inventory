import csv
import io
import re
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import Base, engine, get_db
from app.logging_setup import configure_logging, get_logger
from app.models import CardCache, Deck, DeckCard, InventoryLine
from app.schemas import (
    CardResolveMatch,
    CardResolveOut,
    ClearInventoryResult,
    DeckCardIn,
    DeckCreate,
    DeckCsvImportOut,
    DeckCsvRowError,
    DeckDetailOut,
    DeckOut,
    DeckUpdate,
    ImportResult,
    ImportRowResult,
    InventoryLineOut,
)
from app.services.matcher import match_new_cards
from app.services.scryfall_client import (
    ScryfallClient,
    bulk_ensure_cards_cached,
    ensure_card_cached,
    image_uri_normal_from_payload,
)

Base.metadata.create_all(bind=engine)

configure_logging()
_log = get_logger()

_text_import_progress: dict[int, dict] = {}
_manabox_import_progress: dict[str, dict] = {}

app = FastAPI(title="MTG Inventory API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _norm_bool(val: str | None) -> bool:
    if val is None:
        return False
    v = str(val).strip().lower()
    return v in ("true", "yes", "1", "foil", "y")


def _norm_str(val: str | None) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


_SCRYFALL_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


def _merge_deck_card(
    db: Session,
    deck_id: int,
    scryfall_id: str,
    qty: int,
    *,
    is_commander: bool = False,
    is_sideboard: bool = False,
) -> None:
    if qty <= 0:
        return
    existing = (
        db.query(DeckCard)
        .filter(
            DeckCard.deck_id == deck_id,
            DeckCard.scryfall_id == scryfall_id,
            DeckCard.is_commander == is_commander,
            DeckCard.is_sideboard == is_sideboard,
        )
        .first()
    )
    if existing:
        existing.quantity += qty
    else:
        db.add(
            DeckCard(
                deck_id=deck_id,
                scryfall_id=scryfall_id,
                quantity=qty,
                is_commander=is_commander,
                is_sideboard=is_sideboard,
            )
        )


def _merge_inventory_default(db: Session, scryfall_id: str, qty: int) -> None:
    if qty <= 0:
        return
    foil = False
    language = "en"
    existing = (
        db.query(InventoryLine)
        .filter(
            InventoryLine.scryfall_id == scryfall_id,
            InventoryLine.foil == foil,
            InventoryLine.condition.is_(None),
            InventoryLine.language == language,
        )
        .first()
    )
    if existing:
        existing.quantity += qty
    else:
        db.add(
            InventoryLine(
                scryfall_id=scryfall_id,
                quantity=qty,
                foil=foil,
                condition=None,
                language=language,
            )
        )


def _deck_csv_reader(text: str) -> csv.DictReader:
    reader = csv.DictReader(io.StringIO(text))
    fields = {f.strip().lower() for f in (reader.fieldnames or [])}
    if not fields >= {"scryfall id", "quantity"}:
        raise HTTPException(
            400,
            detail="CSV must include 'Scryfall ID' and 'Quantity' (ManaBox-style columns).",
        )
    return reader


def _apply_deck_csv_rows(
    db: Session,
    deck: Deck,
    reader: csv.DictReader,
    add_to_collection: bool,
) -> list[DeckCsvRowError]:
    errors: list[DeckCsvRowError] = []
    rows = list(reader)
    ids = [
        _norm_str({k.strip().lower(): v for k, v in row.items() if k}.get("scryfall id"))
        for row in rows
    ]
    bulk_ensure_cards_cached(db, [sid for sid in ids if sid])
    for idx, row in enumerate(rows):
        key_map = {k.strip().lower(): v for k, v in row.items() if k}
        sf = _norm_str(key_map.get("scryfall id"))
        if not sf:
            errors.append(DeckCsvRowError(row_index=idx, error="Missing Scryfall ID"))
            continue
        try:
            qty = int(float(key_map.get("quantity") or 0))
        except ValueError:
            qty = 0
        if qty <= 0:
            errors.append(DeckCsvRowError(row_index=idx, error="Invalid quantity"))
            continue
        card = db.get(CardCache, sf)
        if not card:
            errors.append(DeckCsvRowError(row_index=idx, error="Unknown Scryfall ID"))
            continue
        _merge_deck_card(db, deck.id, sf, qty, is_commander=False, is_sideboard=False)
        if add_to_collection:
            _merge_inventory_default(db, sf, qty)
    return errors


_QTY_NAME_LINE = re.compile(r"^(\d+)\s+(.+)$")


def _parse_qty_name_line(line: str) -> tuple[int, str] | None:
    m = _QTY_NAME_LINE.match(line.strip())
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip()


def _resolve_card_name_to_id(db: Session, name: str) -> str | None:
    name = name.strip()
    if not name:
        return None
    client = ScryfallClient()
    data = client.fetch_named(name, exact=True) or client.fetch_named(name, exact=False)
    if data:
        row = client.upsert_cache_from_scryfall(db, data)
        return row.scryfall_id
    found = client.search_cards(name, limit=1)
    if found:
        row = client.upsert_cache_from_scryfall(db, found[0])
        return row.scryfall_id
    return None


def _apply_deck_plaintext(
    db: Session,
    deck: Deck,
    text: str,
    add_to_collection: bool,
    progress_key: int | None = None,
) -> list[DeckCsvRowError]:
    """Parse `qty name` lines; commander zone after last blank line. Line indices in errors are 0-based."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    last_blank_idx: int | None = None
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            last_blank_idx = i
            break
    if last_blank_idx is None:
        ranges: list[tuple[range, bool]] = [(range(0, len(lines)), False)]
    else:
        ranges = [
            (range(0, last_blank_idx), False),
            (range(last_blank_idx + 1, len(lines)), True),
        ]

    card_lines: list[tuple[int, int | None, str, bool]] = []
    for line_range, is_commander in ranges:
        for i in line_range:
            line = lines[i].strip()
            if not line:
                continue
            parsed = _parse_qty_name_line(line)
            if parsed:
                qty, name = parsed
                card_lines.append((i, qty, name, is_commander))
            else:
                card_lines.append((i, None, line, is_commander))

    total = len(card_lines)
    total_qty = sum(q for _, q, _, _ in card_lines if q is not None)
    if progress_key is not None:
        _text_import_progress[progress_key] = {"done": 0, "total": total, "total_qty": total_qty}

    errors: list[DeckCsvRowError] = []
    for idx, (line_idx, qty, name_or_raw, is_commander) in enumerate(card_lines):
        if qty is None:
            errors.append(
                DeckCsvRowError(
                    row_index=line_idx,
                    error=f"Expected 'qty name' (e.g. 1 Lightning Bolt): {name_or_raw[:80]}",
                )
            )
        else:
            sf = _resolve_card_name_to_id(db, name_or_raw)
            if not sf:
                errors.append(DeckCsvRowError(row_index=line_idx, error=f"Card not found: {name_or_raw[:80]}"))
            else:
                _merge_deck_card(db, deck.id, sf, qty, is_commander=is_commander, is_sideboard=False)
                if is_commander and deck.commander_scryfall_id is None:
                    deck.commander_scryfall_id = sf
                if add_to_collection:
                    _merge_inventory_default(db, sf, qty)
        if progress_key is not None:
            _text_import_progress[progress_key]["done"] = idx + 1
    return errors


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/inventory", response_model=list[InventoryLineOut])
def list_inventory(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    sort: str = "name",
):
    query = db.query(InventoryLine).options(joinedload(InventoryLine.card))
    if q or sort == "name":
        query = query.join(CardCache, InventoryLine.scryfall_id == CardCache.scryfall_id)
    if q:
        like = f"%{q}%"
        query = query.filter(CardCache.name.ilike(like))
    if sort == "name":
        query = query.order_by(CardCache.name, InventoryLine.id)
    elif sort == "quantity":
        query = query.order_by(InventoryLine.quantity.desc(), InventoryLine.id)
    elif sort == "set":
        query = query.order_by(InventoryLine.set_code, InventoryLine.collector_number, InventoryLine.id)
    else:
        query = query.order_by(InventoryLine.id)
    return query.all()


@app.delete("/api/inventory/{line_id}")
def delete_inventory_line(line_id: int, db: Annotated[Session, Depends(get_db)]):
    row = db.get(InventoryLine, line_id)
    if row is None:
        raise HTTPException(404, detail="Inventory line not found")
    db.delete(row)
    db.commit()
    _log.info("Deleted inventory line id=%s scryfall_id=%s", line_id, row.scryfall_id)
    return {"ok": True}


@app.post("/api/inventory/clear", response_model=ClearInventoryResult)
def clear_inventory(db: Annotated[Session, Depends(get_db)]):
    """Remove every inventory row. Deck lists and cached Scryfall cards are unchanged."""
    n = db.query(InventoryLine).count()
    db.query(InventoryLine).delete(synchronize_session=False)
    db.commit()
    _log.info("Cleared entire inventory deleted_rows=%s", n)
    return ClearInventoryResult(deleted=n)


@app.get("/api/import/manabox/progress")
def get_manabox_progress(import_key: str = Query(default="")):
    return _manabox_import_progress.get(import_key)


@app.post("/api/import/manabox", response_model=ImportResult)
def import_manabox(
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    import_key: str = Query(default=""),
):
    raw = file.file.read()
    _log.info(
        "ManaBox import started filename=%r size_bytes=%s",
        file.filename,
        len(raw),
    )
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    fields = {f.strip().lower() for f in (reader.fieldnames or [])}
    if not fields >= {"scryfall id", "quantity"}:
        _log.warning("ManaBox import rejected: missing columns have=%s", sorted(fields))
        raise HTTPException(
            400,
            detail="CSV must include at least 'Scryfall ID' and 'Quantity' columns (ManaBox export).",
        )

    all_rows = list(reader)

    ids_in_file = [
        _norm_str({k.strip().lower(): v for k, v in row.items() if k}.get("scryfall id"))
        for row in all_rows
    ]

    if import_key:
        _manabox_import_progress[import_key] = {"batches_done": 0, "batches_total": 0}

    def _on_batch(done: int, total: int) -> None:
        if import_key:
            _manabox_import_progress[import_key] = {"batches_done": done, "batches_total": total}

    try:
        bulk_ensure_cards_cached(
            db,
            [sid for sid in ids_in_file if sid],
            progress_callback=_on_batch if import_key else None,
        )

        # Bulk-load all card data and existing inventory lines before the loop so
        # every row resolves from a Python dict rather than hitting the DB.
        unique_ids = list(dict.fromkeys(sid for sid in ids_in_file if sid))
        card_map: dict[str, CardCache] = (
            {c.scryfall_id: c for c in db.query(CardCache).filter(CardCache.scryfall_id.in_(unique_ids)).all()}
            if unique_ids else {}
        )
        inv_map: dict[tuple, InventoryLine] = (
            {(ln.scryfall_id, ln.foil, ln.condition, ln.language): ln
             for ln in db.query(InventoryLine).filter(InventoryLine.scryfall_id.in_(unique_ids)).all()}
            if unique_ids else {}
        )

        rows_out: list[ImportRowResult] = []
        added_qty = 0

        try:
            for idx, row in enumerate(all_rows):
                key_map = {k.strip().lower(): v for k, v in row.items() if k}
                sf = _norm_str(key_map.get("scryfall id"))
                name = _norm_str(key_map.get("name"))
                if not sf:
                    rows_out.append(
                        ImportRowResult(
                            row_index=idx, scryfall_id=None, name=name, ok=False, error="Missing Scryfall ID"
                        )
                    )
                    continue
                try:
                    qty = int(float(key_map.get("quantity") or 0))
                except ValueError:
                    qty = 0
                if qty <= 0:
                    rows_out.append(
                        ImportRowResult(
                            row_index=idx, scryfall_id=sf, name=name, ok=False, error="Invalid quantity"
                        )
                    )
                    continue

                card = card_map.get(sf)
                if not card:
                    rows_out.append(
                        ImportRowResult(
                            row_index=idx,
                            scryfall_id=sf,
                            name=name,
                            ok=False,
                            error="Scryfall returned no card for this ID",
                        )
                    )
                    continue

                foil = _norm_bool(key_map.get("foil"))
                condition = _norm_str(key_map.get("condition"))
                language = _norm_str(key_map.get("language")) or "en"
                set_code = _norm_str(key_map.get("set code"))
                collector = _norm_str(key_map.get("collector number"))
                manabox_id = _norm_str(key_map.get("manabox id"))
                misprint = _norm_bool(key_map.get("misprint"))
                altered = _norm_bool(key_map.get("altered"))
                price_raw = key_map.get("purchase price")
                try:
                    purchase_price = float(price_raw) if price_raw not in (None, "") else None
                except ValueError:
                    purchase_price = None
                currency = _norm_str(key_map.get("purchase price currency"))

                inv_key = (sf, foil, condition, language)
                existing = inv_map.get(inv_key)
                if existing:
                    existing.quantity += qty
                    existing.set_code = set_code or existing.set_code
                    existing.collector_number = collector or existing.collector_number
                    existing.manabox_id = manabox_id or existing.manabox_id
                    existing.misprint = misprint
                    existing.altered = altered
                    if purchase_price is not None:
                        existing.purchase_price = purchase_price
                    if currency:
                        existing.purchase_currency = currency
                else:
                    new_line = InventoryLine(
                        scryfall_id=sf,
                        quantity=qty,
                        foil=foil,
                        misprint=misprint,
                        altered=altered,
                        condition=condition,
                        language=language,
                        set_code=set_code,
                        collector_number=collector,
                        purchase_price=purchase_price,
                        purchase_currency=currency,
                        manabox_id=manabox_id,
                    )
                    db.add(new_line)
                    inv_map[inv_key] = new_line  # track so duplicate rows in the same CSV merge correctly

                added_qty += qty
                rows_out.append(
                    ImportRowResult(
                        row_index=idx,
                        scryfall_id=sf,
                        name=card.name,
                        ok=True,
                        image_uri_normal=card.image_uri_normal,
                    )
                )

            # Single commit for all inventory changes.
            db.commit()

            # Score all successfully imported cards against decks in one pass —
            # match_new_cards loads all decks once regardless of how many IDs are given.
            ok_ids = [r.scryfall_id for r in rows_out if r.ok and r.scryfall_id]
            if ok_ids:
                all_matches = match_new_cards(db, ok_ids, min_score=35.0)
                for r in rows_out:
                    if r.ok and r.scryfall_id:
                        r.matches = all_matches.get(r.scryfall_id, [])

        except HTTPException:
            raise
        except Exception:
            _log.exception("ManaBox import failed (uncaught exception)")
            raise HTTPException(
                status_code=500,
                detail="Import failed. Check the API console window or backend/logs/spellbinder.log for the traceback.",
            ) from None

        _log.info(
            "ManaBox import finished row_results=%s total_quantity_added=%s",
            len(rows_out),
            added_qty,
        )
        return ImportResult(added_quantity=added_qty, rows=rows_out)
    finally:
        _manabox_import_progress.pop(import_key, None)


@app.get("/api/cards/resolve", response_model=CardResolveOut)
def resolve_card(
    q: str,
    db: Annotated[Session, Depends(get_db)],
):
    query = (q or "").strip()
    if not query:
        raise HTTPException(400, detail="Missing query (card name or Scryfall ID)")
    client = ScryfallClient()
    if _SCRYFALL_ID_RE.match(query):
        row = ensure_card_cached(db, query)
        if not row:
            raise HTTPException(404, detail="Unknown Scryfall card ID")
        return CardResolveOut(
            matches=[
                CardResolveMatch(
                    scryfall_id=row.scryfall_id,
                    name=row.name,
                    type_line=row.type_line,
                    image_uri_normal=row.image_uri_normal,
                )
            ]
        )
    data = client.fetch_named(query, exact=True) or client.fetch_named(query, exact=False)
    if data:
        row = client.upsert_cache_from_scryfall(db, data)
        return CardResolveOut(
            matches=[
                CardResolveMatch(
                    scryfall_id=row.scryfall_id,
                    name=row.name,
                    type_line=row.type_line,
                    image_uri_normal=row.image_uri_normal,
                )
            ]
        )
    found = client.search_cards(query, limit=12)
    if not found:
        raise HTTPException(404, detail="No cards found for that search")
    matches: list[CardResolveMatch] = []
    for d in found:
        sf = d.get("id")
        if not sf:
            continue
        matches.append(
            CardResolveMatch(
                scryfall_id=sf,
                name=d.get("name") or "Unknown",
                type_line=d.get("type_line"),
                image_uri_normal=image_uri_normal_from_payload(d),
            )
        )
    return CardResolveOut(matches=matches)


@app.get("/api/cards/{scryfall_id}/matches")
def card_matches(
    scryfall_id: str,
    db: Annotated[Session, Depends(get_db)],
    min_score: float = Query(35, ge=0, le=100),
):
    ensure_card_cached(db, scryfall_id)
    m = match_new_cards(db, [scryfall_id], min_score=min_score)
    return {"scryfall_id": scryfall_id, "matches": m.get(scryfall_id, [])}


@app.get("/api/decks", response_model=list[DeckOut])
def list_decks(db: Annotated[Session, Depends(get_db)]):
    return db.query(Deck).order_by(Deck.name).all()


@app.post("/api/decks", response_model=DeckDetailOut)
def create_deck(body: DeckCreate, db: Annotated[Session, Depends(get_db)]):
    d = Deck(
        name=body.name,
        format=body.format,
        status=body.status,
        notes=body.notes,
        commander_scryfall_id=body.commander_scryfall_id,
    )
    db.add(d)
    db.flush()
    for c in body.cards:
        ensure_card_cached(db, c.scryfall_id)
        _merge_deck_card(
            db,
            d.id,
            c.scryfall_id,
            c.quantity,
            is_commander=c.is_commander,
            is_sideboard=c.is_sideboard,
        )
        if c.is_commander:
            d.commander_scryfall_id = c.scryfall_id
    db.commit()
    return get_deck(d.id, db)


@app.get("/api/decks/{deck_id}", response_model=DeckDetailOut)
def get_deck(deck_id: int, db: Annotated[Session, Depends(get_db)]):
    d = (
        db.query(Deck)
        .options(joinedload(Deck.cards).joinedload(DeckCard.card))
        .filter(Deck.id == deck_id)
        .first()
    )
    if not d:
        raise HTTPException(404, detail="Deck not found")
    return d


@app.patch("/api/decks/{deck_id}", response_model=DeckDetailOut)
def patch_deck(deck_id: int, body: DeckUpdate, db: Annotated[Session, Depends(get_db)]):
    d = db.get(Deck, deck_id)
    if not d:
        raise HTTPException(404, detail="Deck not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(d, k, v)
    db.commit()
    return get_deck(deck_id, db)


@app.post("/api/decks/{deck_id}/cards", response_model=DeckDetailOut)
def add_deck_cards(deck_id: int, cards: list[DeckCardIn], db: Annotated[Session, Depends(get_db)]):
    d = db.get(Deck, deck_id)
    if not d:
        raise HTTPException(404, detail="Deck not found")

    for c in cards:
        ensure_card_cached(db, c.scryfall_id)
        _merge_deck_card(
            db,
            deck_id,
            c.scryfall_id,
            c.quantity,
            is_commander=c.is_commander,
            is_sideboard=c.is_sideboard,
        )
        if c.is_commander:
            d.commander_scryfall_id = c.scryfall_id
    db.commit()
    return get_deck(deck_id, db)


@app.post("/api/decks/import-csv", response_model=DeckCsvImportOut)
async def import_csv_new_deck(
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    deck_name: str = Form(...),
    format: str = Form("commander"),
    status: str = Form("building"),
    add_to_collection: bool = Form(False),
):
    name = deck_name.strip()
    if not name:
        raise HTTPException(400, detail="Deck name is required")
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = _deck_csv_reader(text)
    d = Deck(name=name, format=format, status=status)
    db.add(d)
    db.flush()
    errors = _apply_deck_csv_rows(db, d, reader, add_to_collection)
    db.commit()
    _log.info("Deck CSV import (new deck) deck_id=%s row_errors=%s add_to_collection=%s", d.id, len(errors), add_to_collection)
    return DeckCsvImportOut(deck=get_deck(d.id, db), row_errors=errors)


@app.post("/api/decks/{deck_id}/import-csv", response_model=DeckCsvImportOut)
async def import_csv_existing_deck(
    deck_id: int,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    add_to_collection: bool = Form(False),
):
    d = db.get(Deck, deck_id)
    if not d:
        raise HTTPException(404, detail="Deck not found")
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = _deck_csv_reader(text)
    errors = _apply_deck_csv_rows(db, d, reader, add_to_collection)
    db.commit()
    _log.info("Deck CSV import (existing) deck_id=%s row_errors=%s add_to_collection=%s", deck_id, len(errors), add_to_collection)
    return DeckCsvImportOut(deck=get_deck(deck_id, db), row_errors=errors)


@app.post("/api/decks/import-text", response_model=DeckCsvImportOut)
def import_text_new_deck(
    db: Annotated[Session, Depends(get_db)],
    text: str = Form(...),
    deck_name: str = Form(...),
    format: str = Form("commander"),
    status: str = Form("building"),
    add_to_collection: bool = Form(False),
):
    """
    Plaintext list: one line per card as `qty name`. Commander zone: lines after the **last**
    blank line (trailing empty lines ignored). Those cards are added with `is_commander` set.
    """
    name = deck_name.strip()
    if not name:
        raise HTTPException(400, detail="Deck name is required")
    body = (text or "").strip()
    if not body:
        raise HTTPException(400, detail="Deck list text is empty")
    d = Deck(name=name, format=format, status=status)
    db.add(d)
    db.flush()
    errors = _apply_deck_plaintext(db, d, text, add_to_collection)
    db.commit()
    _log.info(
        "Deck plaintext import (new deck) deck_id=%s row_errors=%s add_to_collection=%s",
        d.id,
        len(errors),
        add_to_collection,
    )
    return DeckCsvImportOut(deck=get_deck(d.id, db), row_errors=errors)


@app.get("/api/decks/{deck_id}/import-progress")
def get_import_progress(deck_id: int):
    return _text_import_progress.get(deck_id)


@app.post("/api/decks/{deck_id}/import-text", response_model=DeckCsvImportOut)
def import_text_existing_deck(
    deck_id: int,
    db: Annotated[Session, Depends(get_db)],
    text: str = Form(...),
    add_to_collection: bool = Form(False),
):
    d = db.get(Deck, deck_id)
    if not d:
        raise HTTPException(404, detail="Deck not found")
    body = (text or "").strip()
    if not body:
        raise HTTPException(400, detail="Deck list text is empty")
    _log.info("Deck text import (existing) deck_id=%s add_to_collection=%s", deck_id, add_to_collection)
    errors = _apply_deck_plaintext(db, d, text, add_to_collection, progress_key=deck_id)
    db.commit()
    _text_import_progress.pop(deck_id, None)
    return DeckCsvImportOut(deck=get_deck(deck_id, db), row_errors=errors)


@app.delete("/api/decks/{deck_id}/cards/{deck_card_id}", response_model=DeckDetailOut)
def remove_deck_card(deck_id: int, deck_card_id: int, db: Annotated[Session, Depends(get_db)]):
    dc = db.get(DeckCard, deck_card_id)
    if not dc or dc.deck_id != deck_id:
        raise HTTPException(404, detail="Deck card not found")
    db.delete(dc)
    db.commit()
    return get_deck(deck_id, db)


@app.delete("/api/decks/{deck_id}")
def delete_deck(deck_id: int, db: Annotated[Session, Depends(get_db)]):
    d = db.get(Deck, deck_id)
    if not d:
        raise HTTPException(404, detail="Deck not found")
    db.delete(d)
    db.commit()
    return {"ok": True}
