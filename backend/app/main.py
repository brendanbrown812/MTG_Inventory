import csv
import io
import json
import re
import threading
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import Base, SessionLocal, engine, get_db, run_migrations
from app.logging_setup import configure_logging, get_logger
from app.models import (
    CardPrinting, Deck, DeckCard, EnrichmentStats, InventoryLine,
    MechanicProfileRecord, OracleCard, RecommendationRun,
)
from app.embeddings.registry import build_embedding_provider, embedding_provider_is_configured
from app.evaluation.runner import run_local_quality_evaluation
from app.enrichment.base import (
    EnrichmentBatch,
    ProviderUsage,
    card_to_provider_input,
    persist_profile_batch,
    partition_provider_batch,
    profile_from_record,
)
from app.enrichment.pricing import estimate_cost, get_model_prices
from app.enrichment.registry import build_enrichment_provider, provider_is_configured
from app.mechanics.profile import PROFILE_SCHEMA_VERSION, TAXONOMY_VERSION
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
from app.services.commander_engine import analyze_commander_deck, deterministic_roles
from app.services.candidate_retrieval import public_score_summary, retrieve_owned_candidates
from app.services.semantic_index import (
    EMBEDDING_PRICE_PER_MILLION_TOKENS,
    pending_card_embeddings,
    persist_card_embedding_batch,
    semantic_index_status,
)
from app.reasoning.registry import build_strategy_reasoner
from app.review.base import parse_deck_entries, parse_deck_names
from app.review.registry import build_deck_reviewer
from app.services.deck_pipeline import build_deck_with_reasoning
from app.services.deck_optimizer import format_decklist, validate_optimized_deck
from app.services.recommendation_history import (
    candidates_for_run,
    create_recommendation_run,
    record_recommendation_feedback,
)
from app.services.openai_usage import openai_usage_summary
from app.security import api_key_is_valid, has_unprotected_remote_origin, validate_auth_configuration
from app.services.scryfall_client import (
    ScryfallClient,
    bulk_ensure_cards_cached,
    bulk_ensure_cards_cached_by_name,
    bulk_ensure_cards_cached_by_printing,
    ensure_card_cached,
    image_uri_normal_from_payload,
)

Base.metadata.create_all(bind=engine)
run_migrations(engine)

configure_logging()
_log = get_logger()

validate_auth_configuration()
if has_unprotected_remote_origin():
    _log.warning(
        "CORS_ORIGINS includes a remote origin but authentication is not required. "
        "This is acceptable for a backend bound only to 127.0.0.1; set REQUIRE_AUTH=true "
        "before exposing the API to a LAN, tunnel, or public network."
    )

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


_PUBLIC_API_PATHS = {"/api/health", "/api/auth/status"}


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    content_length = request.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > settings.max_request_bytes:
                return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})
    if (
        request.url.path.startswith("/api/")
        and request.url.path not in _PUBLIC_API_PATHS
        and not api_key_is_valid(request.headers.get("X-Spellbinder-Key"))
    ):
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing Spellbinder API key"})
    return await call_next(request)


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


def _validate_upload_size(raw: bytes) -> bytes:
    if len(raw) > settings.max_upload_bytes:
        max_mb = settings.max_upload_bytes / (1024 * 1024)
        raise HTTPException(413, detail=f"Upload exceeds the {max_mb:g} MB limit")
    return raw


def _validate_text_size(value: str, *, ai: bool = False) -> str:
    limit = settings.max_ai_text_chars if ai else settings.max_deck_text_chars
    if len(value) > limit:
        raise HTTPException(413, detail=f"Text input exceeds the {limit:,}-character limit")
    return value


def _require_card_cached(db: Session, scryfall_id: str) -> CardPrinting:
    row = ensure_card_cached(db, scryfall_id)
    if row is None:
        raise HTTPException(400, detail=f"Unknown Scryfall card ID: {scryfall_id}")
    return row


_SCRYFALL_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
    printing = db.get(CardPrinting, scryfall_id)
    if printing is None:
        raise ValueError(f"Card printing is not cached: {scryfall_id}")
    existing = (
        db.query(DeckCard)
        .filter(
            DeckCard.deck_id == deck_id,
            DeckCard.oracle_id == printing.oracle_id,
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
                oracle_id=printing.oracle_id,
                quantity=qty,
                is_commander=is_commander,
                is_sideboard=is_sideboard,
            )
        )
        # SessionLocal disables autoflush; flush so another printing of the
        # same Oracle card in this request merges into this row.
        db.flush()


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
    valid_ids = [sid for sid in ids if sid]
    cache_map = bulk_ensure_cards_cached(db, valid_ids)

    # Preload existing deck cards and inventory lines for in-memory merge.
    existing_dc: dict[tuple, DeckCard] = {
        (dc.oracle_id, dc.is_commander, dc.is_sideboard): dc
        for dc in db.query(DeckCard).filter(DeckCard.deck_id == deck.id).all()
    }
    inv_map: dict[tuple, InventoryLine] = {}
    if add_to_collection and valid_ids:
        inv_map = {
            (il.scryfall_id, il.foil, il.condition, il.language): il
            for il in db.query(InventoryLine)
            .filter(InventoryLine.scryfall_id.in_(valid_ids))
            .all()
        }

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
        if not cache_map.get(sf):
            errors.append(DeckCsvRowError(row_index=idx, error="Unknown Scryfall ID"))
            continue

        printing = cache_map[sf]
        dc_key = (printing.oracle_id, False, False)
        if dc_key in existing_dc:
            existing_dc[dc_key].quantity += qty
        else:
            dc = DeckCard(
                deck_id=deck.id, scryfall_id=sf, oracle_id=printing.oracle_id,
                quantity=qty, is_commander=False, is_sideboard=False,
            )
            db.add(dc)
            existing_dc[dc_key] = dc

        if add_to_collection:
            inv_key = (sf, False, None, "en")
            if inv_key in inv_map:
                inv_map[inv_key].quantity += qty
            else:
                il = InventoryLine(scryfall_id=sf, quantity=qty, foil=False, condition=None, language="en")
                db.add(il)
                inv_map[inv_key] = il

    return errors


_QTY_NAME_LINE = re.compile(r"^(\d+)\s+(.+)$")
# Matches Moxfield/Archidekt export suffix: "Card Name (SET) collector_number [*F*]"
_SET_COLLECTOR_SUFFIX = re.compile(
    r"^(.*?)\s+\(([A-Z0-9]{2,6})\)\s+(\S+?)\s*(\*F\*)?\s*$",
    re.IGNORECASE,
)


def _parse_qty_name_details(
    line: str,
) -> tuple[int, str, str | None, str | None, bool] | None:
    """Parse a quantity/name line while retaining optional printing hints."""
    m = _QTY_NAME_LINE.match(line.strip())
    if not m:
        return None
    qty = int(m.group(1))
    raw_name = m.group(2).strip()
    sm = _SET_COLLECTOR_SUFFIX.match(raw_name)
    if not sm:
        return qty, raw_name, None, None, False
    return (
        qty,
        sm.group(1).strip(),
        sm.group(2).lower(),
        sm.group(3),
        bool(sm.group(4)),
    )


def _parse_qty_name_line(line: str) -> tuple[int, str] | None:
    parsed = _parse_qty_name_details(line)
    return (parsed[0], parsed[1]) if parsed else None


def _deck_plaintext_lines(
    text: str,
) -> list[tuple[int, int | None, str, bool, str | None, str | None, bool]]:
    """Return parsed lines; cards after the last blank line are commanders."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    last_blank_idx: int | None = None
    for index in range(len(lines) - 1, -1, -1):
        if not lines[index].strip():
            last_blank_idx = index
            break
    ranges = (
        [(range(0, len(lines)), False)]
        if last_blank_idx is None
        else [
            (range(0, last_blank_idx), False),
            (range(last_blank_idx + 1, len(lines)), True),
        ]
    )

    parsed_lines = []
    for line_range, is_commander in ranges:
        for index in line_range:
            line = lines[index].strip()
            if not line:
                continue
            parsed = _parse_qty_name_details(line)
            if parsed:
                qty, name, set_code, collector_number, foil = parsed
                parsed_lines.append(
                    (index, qty, name, is_commander, set_code, collector_number, foil)
                )
            else:
                parsed_lines.append((index, None, line, is_commander, None, None, False))
    return parsed_lines


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
    card_lines: list[tuple[int, int | None, str, bool]] = []
    for line_idx, qty, name, is_commander, _set_code, _collector, _foil in _deck_plaintext_lines(text):
        card_lines.append((line_idx, qty, name, is_commander))

    total = len(card_lines)
    total_qty = sum(q for _, q, _, _ in card_lines if q is not None)

    # Bulk-resolve all card names: ceil(N/75) Scryfall requests instead of N sequential calls.
    names_to_resolve = [name for _, qty, name, _ in card_lines if qty is not None]

    def _on_batch(done: int, total_batches: int) -> None:
        if progress_key is not None:
            _text_import_progress[progress_key] = {
                "done": 0,
                "total": total,
                "total_qty": total_qty,
                "batches_done": done,
                "batches_total": total_batches,
            }

    if progress_key is not None:
        _text_import_progress[progress_key] = {
            "done": 0, "total": total, "total_qty": total_qty,
            "batches_done": 0, "batches_total": 0,
        }

    _t0 = time.monotonic()
    name_map = bulk_ensure_cards_cached_by_name(
        db, names_to_resolve,
        progress_callback=_on_batch if progress_key is not None else None,
    )
    _log.info(
        "plaintext import bulk-name-fetch: %.2fs  names=%d  resolved=%d  misses=%d",
        time.monotonic() - _t0,
        len(names_to_resolve),
        len(name_map),
        len(names_to_resolve) - len(name_map),
    )

    # Preload existing deck cards for in-memory merge.
    existing_dc: dict[tuple, DeckCard] = {
        (dc.oracle_id, dc.is_commander, dc.is_sideboard): dc
        for dc in db.query(DeckCard).filter(DeckCard.deck_id == deck.id).all()
    }

    # Preload inventory lines for all already-resolved IDs.
    resolved_ids = {row.scryfall_id for row in name_map.values()}
    inv_map: dict[tuple, InventoryLine] = {}
    if add_to_collection and resolved_ids:
        inv_map = {
            (il.scryfall_id, il.foil, il.condition, il.language): il
            for il in db.query(InventoryLine)
            .filter(InventoryLine.scryfall_id.in_(list(resolved_ids)))
            .all()
        }

    # Switch progress to the per-card loop phase.
    if progress_key is not None:
        _text_import_progress[progress_key] = {"done": 0, "total": total, "total_qty": total_qty}

    _t1 = time.monotonic()
    fallback_count = 0
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
            card = name_map.get(name_or_raw.lower())
            if card is None:
                # Bulk lookup missed (e.g. fuzzy name mismatch) — fall back to individual lookup.
                fallback_count += 1
                _log.debug("plaintext import fallback lookup: %r", name_or_raw)
                sf = _resolve_card_name_to_id(db, name_or_raw)
                if sf:
                    card = db.get(CardPrinting, sf)
                    if card:
                        name_map[name_or_raw.lower()] = card  # cache for any duplicates

            if card is None:
                errors.append(DeckCsvRowError(row_index=line_idx, error=f"Card not found: {name_or_raw[:80]}"))
            else:
                sf = card.scryfall_id
                dc_key = (card.oracle_id, is_commander, False)
                if dc_key in existing_dc:
                    existing_dc[dc_key].quantity += qty
                else:
                    dc = DeckCard(
                        deck_id=deck.id, scryfall_id=sf, oracle_id=card.oracle_id, quantity=qty,
                        is_commander=is_commander, is_sideboard=False,
                    )
                    db.add(dc)
                    existing_dc[dc_key] = dc

                if is_commander and deck.commander_scryfall_id is None:
                    deck.commander_scryfall_id = sf
                    deck.commander_oracle_id = card.oracle_id

                if add_to_collection:
                    inv_key = (sf, False, None, "en")
                    if inv_key in inv_map:
                        inv_map[inv_key].quantity += qty
                    else:
                        il = InventoryLine(scryfall_id=sf, quantity=qty, foil=False, condition=None, language="en")
                        db.add(il)
                        inv_map[inv_key] = il

        if progress_key is not None:
            _text_import_progress[progress_key]["done"] = idx + 1

    _log.info(
        "plaintext import loop: %.2fs  cards=%d  fallbacks=%d  errors=%d",
        time.monotonic() - _t1,
        total,
        fallback_count,
        len(errors),
    )
    return errors


class _DeckTextPreviewRequest(BaseModel):
    text: str = Field(min_length=1)


def _preview_deck_plaintext(db: Session, text: str) -> dict:
    parsed_lines = _deck_plaintext_lines(text)
    exact_identifiers = [
        (set_code, collector_number)
        for _, qty, _, _, set_code, collector_number, _ in parsed_lines
        if qty is not None and set_code and collector_number
    ]
    try:
        exact_map = bulk_ensure_cards_cached_by_printing(db, exact_identifiers)
    except httpx.HTTPError as exc:
        _log.warning("Moxfield exact-printing lookup unavailable: %s", exc)
        exact_map = {}

    unresolved_names = []
    for _, qty, name, _, set_code, collector_number, _ in parsed_lines:
        if qty is None:
            continue
        key = (
            (set_code or "").lower(),
            (collector_number or "").lower(),
        )
        if not set_code or not collector_number or key not in exact_map:
            unresolved_names.append(name)
    unique_lower_names = {name.lower() for name in unresolved_names}
    local_name_rows = (
        db.query(CardPrinting)
        .options(joinedload(CardPrinting.oracle))
        .join(OracleCard)
        .filter(func.lower(OracleCard.name).in_(unique_lower_names))
        .all()
        if unique_lower_names else []
    )
    name_map: dict[str, CardPrinting] = {}
    for row in local_name_rows:
        name_map.setdefault(row.name.lower(), row)

    names_to_fetch = [name for name in unresolved_names if name.lower() not in name_map]
    if names_to_fetch:
        try:
            name_map.update(bulk_ensure_cards_cached_by_name(db, names_to_fetch))
        except httpx.HTTPError as exc:
            _log.warning("Moxfield name lookup unavailable: %s", exc)

    owned_rows = (
        db.query(CardPrinting.oracle_id, func.sum(InventoryLine.quantity))
        .join(InventoryLine, InventoryLine.scryfall_id == CardPrinting.scryfall_id)
        .group_by(CardPrinting.oracle_id)
        .all()
    )
    owned_by_oracle = {oracle_id: int(quantity or 0) for oracle_id, quantity in owned_rows}

    cards = []
    errors = []
    for line_idx, qty, name, is_commander, set_code, collector_number, foil in parsed_lines:
        if qty is None:
            errors.append({
                "row_index": line_idx,
                "error": f"Expected 'qty name': {name[:80]}",
            })
            continue
        exact_key = (
            (set_code or "").lower(),
            (collector_number or "").lower(),
        )
        card = exact_map.get(exact_key) if set_code and collector_number else None
        if card is None:
            card = name_map.get(name.lower())
        if card is None:
            try:
                card_id = _resolve_card_name_to_id(db, name)
            except httpx.HTTPError as exc:
                _log.warning("Moxfield fallback lookup unavailable for %r: %s", name, exc)
                card_id = None
            card = db.get(CardPrinting, card_id) if card_id else None
        if card is None:
            errors.append({"row_index": line_idx, "error": f"Card not found: {name[:80]}"})
            continue
        cards.append({
            "line_index": line_idx,
            "quantity": qty,
            "scryfall_id": card.scryfall_id,
            "oracle_id": card.oracle_id,
            "name": card.name,
            "type_line": card.type_line,
            "colors": card.colors,
            "image_uri_normal": card.image_uri_normal,
            "set_code": card.set_code or set_code,
            "collector_number": card.collector_number or collector_number,
            "foil": foil,
            "is_commander": is_commander,
            "owned_quantity": owned_by_oracle.get(card.oracle_id, 0),
        })
    return {
        "cards": cards,
        "row_errors": errors,
        "total_quantity": sum(card["quantity"] for card in cards),
    }


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status(request: Request):
    required = bool(settings.app_api_key)
    return {
        "required": required,
        "authenticated": not required or api_key_is_valid(request.headers.get("X-Spellbinder-Key")),
    }


@app.get("/api/inventory", response_model=list[InventoryLineOut])
def list_inventory(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    sort: str = "name",
):
    query = db.query(InventoryLine).options(joinedload(InventoryLine.card))
    if q or sort == "name":
        query = query.join(CardPrinting).join(OracleCard)
    if q:
        like = f"%{q}%"
        query = query.filter(OracleCard.name.ilike(like))
    if sort == "name":
        query = query.order_by(OracleCard.name, InventoryLine.id)
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
def get_manabox_progress(import_key: str = Query(default="", max_length=100)):
    return _manabox_import_progress.get(import_key)


@app.post("/api/import/manabox", response_model=ImportResult)
def import_manabox(
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    import_key: str = Query(default="", max_length=100),
):
    raw = _validate_upload_size(file.file.read(settings.max_upload_bytes + 1))
    _log.info(
        "ManaBox import started import_key=%s filename=%r size_bytes=%s",
        import_key or "none",
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
        _manabox_import_progress[import_key] = {
            "status": "running", "stage": "hydrating_cards",
            "batches_done": 0, "batches_total": 0,
        }

    def _on_batch(done: int, total: int) -> None:
        if import_key:
            _manabox_import_progress[import_key] = {
                "status": "running", "stage": "hydrating_cards",
                "batches_done": done, "batches_total": total,
            }

    stage = "hydrating_cards"
    try:
        bulk_ensure_cards_cached(
            db,
            [sid for sid in ids_in_file if sid],
            progress_callback=_on_batch if import_key else None,
            refresh_stale=False,
        )

        stage = "assembling_inventory"
        if import_key:
            current_progress = _manabox_import_progress.get(import_key, {})
            _manabox_import_progress[import_key] = {
                **current_progress, "status": "running", "stage": stage,
            }

        # Bulk-load all card data and existing inventory lines before the loop so
        # every row resolves from a Python dict rather than hitting the DB.
        unique_ids = list(dict.fromkeys(sid for sid in ids_in_file if sid))
        card_map: dict[str, CardPrinting] = (
            {c.scryfall_id: c for c in db.query(CardPrinting).filter(CardPrinting.scryfall_id.in_(unique_ids)).all()}
            if unique_ids else {}
        )
        inv_map: dict[tuple, InventoryLine] = (
            {(ln.scryfall_id, ln.foil, ln.condition, ln.language): ln
             for ln in db.query(InventoryLine).filter(InventoryLine.scryfall_id.in_(unique_ids)).all()}
            if unique_ids else {}
        )

        rows_out: list[ImportRowResult] = []
        added_qty = 0

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

        # Single commit keeps the inventory portion atomic.
        db.commit()
        _log.info(
            "ManaBox inventory committed import_key=%s rows=%d quantity=%d",
            import_key or "none",
            len(rows_out),
            added_qty,
        )

        # Recommendation matching is useful but must never turn a successful
        # inventory commit into a reported import failure.
        stage = "matching_decks"
        ok_ids = list(dict.fromkeys(
            r.scryfall_id for r in rows_out if r.ok and r.scryfall_id
        ))
        if ok_ids:
            try:
                all_matches = match_new_cards(db, ok_ids, min_score=35.0)
                for r in rows_out:
                    if r.ok and r.scryfall_id:
                        r.matches = all_matches.get(r.scryfall_id, [])
            except Exception:
                _log.exception(
                    "ManaBox deck matching failed after inventory commit import_key=%s; continuing",
                    import_key or "none",
                )

        _log.info(
            "ManaBox import finished import_key=%s row_results=%s total_quantity_added=%s",
            import_key or "none",
            len(rows_out),
            added_qty,
        )
        if import_key:
            _manabox_import_progress[import_key] = {
                "status": "complete", "stage": "complete",
                "batches_done": _manabox_import_progress.get(import_key, {}).get("batches_done", 0),
                "batches_total": _manabox_import_progress.get(import_key, {}).get("batches_total", 0),
            }
        return ImportResult(added_quantity=added_qty, rows=rows_out)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        _log.exception(
            "ManaBox import failed import_key=%s stage=%s filename=%r rows=%d",
            import_key or "none",
            stage,
            file.filename,
            len(all_rows),
        )
        if import_key:
            current_progress = _manabox_import_progress.get(import_key, {})
            _manabox_import_progress[import_key] = {
                **current_progress,
                "status": "failed",
                "stage": stage,
                "error": f"{type(exc).__name__}: {exc}",
            }
        status_code = 502 if isinstance(exc, httpx.HTTPError) else 500
        raise HTTPException(
            status_code=status_code,
            detail=(
                f"Import failed during {stage}. The failure was logged to "
                "backend/logs/spellbinder.log; rerunning will reuse cached Scryfall batches."
            ),
        ) from None


@app.get("/api/cards/resolve", response_model=CardResolveOut)
def resolve_card(
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(min_length=1, max_length=500),
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


@app.get("/api/cards/{scryfall_id}/decks")
def card_in_decks(scryfall_id: str, db: Annotated[Session, Depends(get_db)]):
    """Return the decks that actually contain this card."""
    printing = db.get(CardPrinting, scryfall_id)
    if printing is None:
        return []
    rows = (
        db.query(DeckCard)
        .filter(DeckCard.oracle_id == printing.oracle_id)
        .options(joinedload(DeckCard.deck))
        .all()
    )
    return [
        {"deck_id": dc.deck_id, "deck_name": dc.deck.name, "is_commander": dc.is_commander}
        for dc in rows
    ]


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
    commander_oracle_id = None
    if body.commander_scryfall_id:
        commander_oracle_id = _require_card_cached(
            db, body.commander_scryfall_id
        ).oracle_id
    d = Deck(
        name=body.name,
        format=body.format,
        status=body.status,
        notes=body.notes,
        commander_scryfall_id=body.commander_scryfall_id,
        commander_oracle_id=commander_oracle_id,
    )
    db.add(d)
    db.flush()
    for c in body.cards:
        _require_card_cached(db, c.scryfall_id)
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
            d.commander_oracle_id = db.get(CardPrinting, c.scryfall_id).oracle_id
    db.commit()
    return get_deck(d.id, db)


@app.post("/api/decks/preview-text")
def preview_deck_text(
    body: _DeckTextPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """Resolve a Moxfield/plaintext list without creating or changing a deck."""
    _validate_text_size(body.text)
    if not body.text.strip():
        raise HTTPException(400, detail="Deck list text is empty")
    return _preview_deck_plaintext(db, body.text)


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


@app.get("/api/decks/{deck_id}/analysis")
def analyze_deck(deck_id: int, db: Annotated[Session, Depends(get_db)]):
    """Run deterministic Commander legality, availability, and health checks."""
    deck = (
        db.query(Deck)
        .options(
            joinedload(Deck.cards).joinedload(DeckCard.card).joinedload(CardPrinting.oracle),
            joinedload(Deck.cards).joinedload(DeckCard.oracle_card),
        )
        .filter(Deck.id == deck_id)
        .first()
    )
    if not deck:
        raise HTTPException(404, detail="Deck not found")
    if (deck.format or "").lower() not in {"commander", "edh"}:
        raise HTTPException(400, detail="Deterministic analysis currently supports Commander decks")
    return analyze_commander_deck(db, deck)


@app.patch("/api/decks/{deck_id}", response_model=DeckDetailOut)
def patch_deck(deck_id: int, body: DeckUpdate, db: Annotated[Session, Depends(get_db)]):
    d = db.get(Deck, deck_id)
    if not d:
        raise HTTPException(404, detail="Deck not found")
    data = body.model_dump(exclude_unset=True)
    if "commander_scryfall_id" in data:
        commander_id = data["commander_scryfall_id"]
        d.commander_oracle_id = (
            _require_card_cached(db, commander_id).oracle_id if commander_id else None
        )
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
        _require_card_cached(db, c.scryfall_id)
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
            d.commander_oracle_id = db.get(CardPrinting, c.scryfall_id).oracle_id
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
    raw = _validate_upload_size(await file.read(settings.max_upload_bytes + 1))
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
    raw = _validate_upload_size(await file.read(settings.max_upload_bytes + 1))
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
    _validate_text_size(text)
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
    _validate_text_size(text)
    body = (text or "").strip()
    if not body:
        raise HTTPException(400, detail="Deck list text is empty")
    _log.info("Deck text import (existing) deck_id=%s add_to_collection=%s", deck_id, add_to_collection)
    try:
        errors = _apply_deck_plaintext(db, d, text, add_to_collection, progress_key=deck_id)
        db.commit()
        return DeckCsvImportOut(deck=get_deck(deck_id, db), row_errors=errors)
    finally:
        _text_import_progress.pop(deck_id, None)


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


# ══════════════════════════════════════════════════════════════════════════════
# Enrichment endpoints — Scryfall backfill + structured mechanic profiles
# ══════════════════════════════════════════════════════════════════════════════

_enrichment_jobs: dict[str, dict] = {}
_enrichment_jobs_lock = threading.Lock()
_MAX_ENRICHMENT_JOB_HISTORY = 100


def _start_enrichment_job(job_type: str, total: int) -> str:
    with _enrichment_jobs_lock:
        if any(job.get("status") == "running" for job in _enrichment_jobs.values()):
            raise HTTPException(409, detail="An enrichment job is already running")

        finished = [job_id for job_id, job in _enrichment_jobs.items() if job.get("status") != "running"]
        excess = len(_enrichment_jobs) - _MAX_ENRICHMENT_JOB_HISTORY + 1
        for old_job_id in finished[:max(0, excess)]:
            _enrichment_jobs.pop(old_job_id, None)

        job_id = str(uuid.uuid4())
        _enrichment_jobs[job_id] = {
            "status": "running",
            "type": job_type,
            "processed": 0,
            "total": total,
        }
        return job_id


def _update_enrichment_job(job_id: str, **values) -> None:
    with _enrichment_jobs_lock:
        job = _enrichment_jobs.get(job_id)
        if job is not None:
            job.update(values)


def _select_enrichment_batch(db: Session, batch_size: int) -> list[OracleCard]:
    """
    Select cards without a current profile for this schema/taxonomy, prioritizing
    common Scryfall keywords first, then keyword-less cards ordered by ID.
    Pure Python sort after a single bulk query — fine for personal collection sizes.
    """
    profiled_ids = (
        db.query(MechanicProfileRecord.oracle_id)
        .filter(
            MechanicProfileRecord.is_current.is_(True),
            MechanicProfileRecord.schema_version == PROFILE_SCHEMA_VERSION,
            MechanicProfileRecord.taxonomy_version == TAXONOMY_VERSION,
        )
    )
    unprofiled: list[OracleCard] = (
        db.query(OracleCard)
        .filter(OracleCard.oracle_id.notin_(profiled_ids))
        .all()
    )
    if not unprofiled:
        return []

    with_kw  = [c for c in unprofiled if c.keywords and c.keywords not in ("[]", "null", "")]
    no_kw    = [c for c in unprofiled if not c.keywords or c.keywords in ("[]", "null", "")]

    kw_counts: Counter = Counter()
    for c in with_kw:
        try:
            for kw in json.loads(c.keywords):
                kw_counts[kw] += 1
        except Exception:
            pass

    def _max_freq(c: OracleCard) -> int:
        try:
            return max((kw_counts[kw] for kw in json.loads(c.keywords)), default=0)
        except Exception:
            return 0

    with_kw.sort(key=_max_freq, reverse=True)

    selected = with_kw[:batch_size]
    if len(selected) < batch_size:
        selected += no_kw[:batch_size - len(selected)]
    return selected


def _run_scryfall_backfill(job_id: str, batch_size: int) -> None:
    db = SessionLocal()
    try:
        cards: list[CardPrinting] = (
            db.query(CardPrinting)
            .join(OracleCard)
            .filter(OracleCard.keywords.is_(None))
            .group_by(OracleCard.oracle_id)
            .limit(batch_size)
            .all()
        )
        total = len(cards)
        _update_enrichment_job(job_id, total=total, processed=0)

        client = ScryfallClient()

        # Use batch endpoint (75 at a time) — much faster than per-card calls
        ids = [c.scryfall_id for c in cards]
        batch_size_sf = 75

        done = 0
        failed = 0
        for i in range(0, len(ids), batch_size_sf):
            chunk_ids = ids[i : i + batch_size_sf]
            found, not_found = client.fetch_cards_collection(chunk_ids)
            for data in found:
                client.upsert_cache_from_scryfall(db, data, commit=False)
            db.commit()
            done += len(found)
            failed += len(not_found)
            _update_enrichment_job(job_id, processed=done, failed=failed)

        _update_enrichment_job(job_id, status="done")
        _log.info("Scryfall backfill done job_id=%s cards=%s", job_id, total)
    except Exception as exc:
        _update_enrichment_job(job_id, status="error", error=str(exc))
        _log.exception("Scryfall backfill failed job_id=%s", job_id)
    finally:
        db.close()


def _run_structured_enrichment(job_id: str, batch_size: int) -> None:
    db = SessionLocal()
    try:
        provider = build_enrichment_provider()
        cards = _select_enrichment_batch(db, batch_size)
        total = len(cards)
        _update_enrichment_job(job_id, total=total, processed=0)

        batch_id = str(uuid.uuid4())
        processed = 0
        failed_cards: list[str] = []
        chunk_size = 12

        for i in range(0, total, chunk_size):
            chunk = cards[i : i + chunk_size]
            provider_cards = [card_to_provider_input(card) for card in chunk]
            batch = provider.enrich(provider_cards)
            valid_profiles, failures = partition_provider_batch(provider_cards, batch)
            if valid_profiles:
                fraction = len(valid_profiles) / max(1, len(provider_cards))
                valid_usage = ProviderUsage(
                    input_tokens=round(batch.usage.input_tokens * fraction),
                    output_tokens=round(batch.usage.output_tokens * fraction),
                )
                persist_profile_batch(
                    db,
                    provider,
                    EnrichmentBatch(profiles=valid_profiles, usage=valid_usage),
                )

            db.add(EnrichmentStats(
                batch_id=batch_id,
                model=f"{provider.provider_name}:{provider.model_name}",
                input_tokens=batch.usage.input_tokens,
                output_tokens=batch.usage.output_tokens,
                cards_processed=len(chunk),
            ))
            db.commit()

            retry_by_id = {card.oracle_id: card for card in provider_cards}
            recovered = 0
            retry_items = [
                (oracle_id, reason)
                for oracle_id, reason in failures.items()
                if oracle_id in retry_by_id
            ]
            # A high failure ratio indicates a systematic schema/provider issue,
            # not independent card defects. Never amplify one paid request into a
            # retry storm like the original 48-card incident.
            max_isolated_retries = min(3, max(1, len(provider_cards) // 3))
            if len(retry_items) > max_isolated_retries:
                failed_cards.extend(retry_by_id[oracle_id].name for oracle_id, _ in retry_items)
                _log.error(
                    "Enrichment retry circuit opened job_id=%s invalid=%s chunk=%s limit=%s",
                    job_id, len(retry_items), len(provider_cards), max_isolated_retries,
                )
                retry_items = []

            for oracle_id, reason in retry_items:
                retry_card = retry_by_id.get(oracle_id)
                if retry_card is None:
                    _log.warning("Ignoring enrichment batch anomaly job_id=%s detail=%s", job_id, reason)
                    continue
                try:
                    retry_batch = provider.enrich([retry_card])
                    retry_valid, retry_failures = partition_provider_batch(
                        [retry_card], retry_batch
                    )
                    db.add(EnrichmentStats(
                        batch_id=batch_id,
                        model=f"{provider.provider_name}:{provider.model_name}",
                        input_tokens=retry_batch.usage.input_tokens,
                        output_tokens=retry_batch.usage.output_tokens,
                        cards_processed=1,
                    ))
                    if retry_valid:
                        persist_profile_batch(
                            db,
                            provider,
                            EnrichmentBatch(profiles=retry_valid, usage=retry_batch.usage),
                        )
                        recovered += 1
                    else:
                        failed_cards.append(retry_card.name)
                        _log.warning(
                            "Enrichment retry rejected job_id=%s card=%s detail=%s",
                            job_id, retry_card.name,
                            retry_failures.get(oracle_id, "invalid provider response"),
                        )
                    db.commit()
                except Exception as retry_exc:
                    db.rollback()
                    failed_cards.append(retry_card.name)
                    _log.warning(
                        "Enrichment retry failed job_id=%s card=%s error=%s",
                        job_id, retry_card.name, type(retry_exc).__name__, exc_info=True,
                    )

            processed += len(valid_profiles) + recovered
            _update_enrichment_job(
                job_id,
                processed=processed,
                failed=len(failed_cards),
                failed_cards=list(failed_cards),
            )
            _log.info(
                "Structured enrichment chunk done job_id=%s processed=%s/%s provider=%s model=%s",
                job_id, processed, total, provider.provider_name, provider.model_name,
            )

        _update_enrichment_job(
            job_id,
            status="done",
            failed=len(failed_cards),
            failed_cards=list(failed_cards),
        )
    except Exception as exc:
        _update_enrichment_job(job_id, status="error", error=str(exc))
        _log.exception("Structured enrichment job failed job_id=%s", job_id)
    finally:
        db.close()


def _run_semantic_index(job_id: str, batch_size: int) -> None:
    db = SessionLocal()
    try:
        provider = build_embedding_provider()
        pending = pending_card_embeddings(db, limit=batch_size)
        total = len(pending)
        _update_enrichment_job(job_id, total=total, processed=0, input_tokens=0)
        processed = 0
        input_tokens = 0
        chunk_size = max(1, min(settings.embedding_request_batch_size, 2_048))
        for offset in range(0, total, chunk_size):
            chunk = pending[offset : offset + chunk_size]
            input_tokens += persist_card_embedding_batch(db, provider, chunk)
            db.commit()
            processed += len(chunk)
            _update_enrichment_job(
                job_id,
                processed=processed,
                input_tokens=input_tokens,
                estimated_cost=round(
                    input_tokens * EMBEDDING_PRICE_PER_MILLION_TOKENS / 1_000_000,
                    6,
                ),
            )
            _log.info(
                "Semantic index chunk done job_id=%s processed=%s/%s model=%s dimensions=%s",
                job_id, processed, total, provider.model_name, provider.dimensions,
            )
        _update_enrichment_job(job_id, status="done")
    except Exception as exc:
        db.rollback()
        _update_enrichment_job(job_id, status="error", error=str(exc))
        _log.exception("Semantic indexing job failed job_id=%s", job_id)
    finally:
        db.close()


@app.get("/api/enrichment/status")
def enrichment_status(db: Annotated[Session, Depends(get_db)]):
    total = db.query(OracleCard).count()
    profiled = (
        db.query(MechanicProfileRecord.oracle_id)
        .filter(
            MechanicProfileRecord.is_current.is_(True),
            MechanicProfileRecord.schema_version == PROFILE_SCHEMA_VERSION,
            MechanicProfileRecord.taxonomy_version == TAXONOMY_VERSION,
        )
        .distinct()
        .count()
    )
    keywords_miss = db.query(OracleCard).filter(OracleCard.keywords.is_(None)).count()
    stats_model = f"{settings.enrichment_provider}:{settings.enrichment_model}"

    stats = db.execute(sa_text("""
        SELECT SUM(input_tokens), SUM(output_tokens), SUM(cards_processed)
        FROM tagging_stats
        WHERE model = :model
    """), {"model": stats_model}).fetchone()

    avg_in = avg_out = None
    if stats and stats[2]:
        avg_in  = stats[0] / stats[2]
        avg_out = stats[1] / stats[2]

    unprofiled = total - profiled
    est_cost = estimate_cost(
        settings.enrichment_provider,
        settings.enrichment_model,
        unprofiled,
        avg_in,
        avg_out,
    )
    prices = get_model_prices(settings.enrichment_provider, settings.enrichment_model)

    return {
        "total_cards":                total,
        "profiled_cards":             profiled,
        "unprofiled_cards":           unprofiled,
        "keywords_missing":           keywords_miss,
        "profile_schema_version":     PROFILE_SCHEMA_VERSION,
        "taxonomy_version":           TAXONOMY_VERSION,
        "enrichment_provider":        settings.enrichment_provider,
        "enrichment_model":           settings.enrichment_model,
        "provider_configured":        provider_is_configured(),
        "paid_requests_enabled":      settings.openai_requests_enabled,
        "model_prices":               prices,
        "avg_input_tokens_per_card":  avg_in,
        "avg_output_tokens_per_card": avg_out,
        "estimated_cost_all_unprofiled": round(est_cost, 4),
        **semantic_index_status(db),
    }


@app.get("/api/openai/usage")
def openai_usage():
    """Return the local cost-control ledger; credentials are never included."""
    return openai_usage_summary()


class _ScryfallBatchRequest(BaseModel):
    batch_size: int = Field(ge=1, le=settings.max_scryfall_batch_size)


class _EnrichmentBatchRequest(BaseModel):
    batch_size: int = Field(ge=1, le=settings.max_enrichment_batch_size)


class _EmbeddingBatchRequest(BaseModel):
    batch_size: int = Field(ge=1, le=settings.max_embedding_batch_size)


@app.post("/api/enrichment/backfill-scryfall")
def start_scryfall_backfill(body: _ScryfallBatchRequest, background_tasks: BackgroundTasks):
    """Re-fetch Scryfall data for cards missing keywords. Free — no AI cost."""
    job_id = _start_enrichment_job("scryfall_backfill", 0)
    background_tasks.add_task(_run_scryfall_backfill, job_id, body.batch_size)
    return {"job_id": job_id}


@app.post("/api/enrichment/run")
def start_structured_enrichment(body: _EnrichmentBatchRequest, background_tasks: BackgroundTasks):
    """Create versioned structured mechanic profiles with the configured provider."""
    if not provider_is_configured():
        if settings.enrichment_provider == "openai" and not settings.openai_requests_enabled:
            detail = "Paid OpenAI requests are disabled by OPENAI_REQUESTS_ENABLED"
        else:
            detail = f"Enrichment provider {settings.enrichment_provider!r} is not configured"
        raise HTTPException(
            400,
            detail=detail,
        )
    job_id = _start_enrichment_job("structured_mechanic_profiles", body.batch_size)
    background_tasks.add_task(_run_structured_enrichment, job_id, body.batch_size)
    return {"job_id": job_id}


@app.post("/api/enrichment/index-embeddings")
def start_semantic_index(body: _EmbeddingBatchRequest, background_tasks: BackgroundTasks):
    """Build or refresh the persistent Oracle-card semantic index."""
    if not embedding_provider_is_configured():
        if settings.embedding_provider == "openai" and not settings.openai_requests_enabled:
            detail = "Paid OpenAI requests are disabled by OPENAI_REQUESTS_ENABLED"
        else:
            detail = f"Embedding provider {settings.embedding_provider!r} is not configured"
        raise HTTPException(400, detail=detail)
    job_id = _start_enrichment_job("semantic_embeddings", body.batch_size)
    background_tasks.add_task(_run_semantic_index, job_id, body.batch_size)
    return {"job_id": job_id}


@app.get("/api/enrichment/progress/{job_id}")
def enrichment_progress(job_id: str):
    with _enrichment_jobs_lock:
        job = dict(_enrichment_jobs[job_id]) if job_id in _enrichment_jobs else None
    if job is None:
        raise HTTPException(404, detail="Job not found")
    return job


@app.get("/api/enrichment/sample")
def enrichment_sample(
    db: Annotated[Session, Depends(get_db)],
    n: int = Query(default=20, ge=1, le=100),
):
    """
    Return recently-created structured profiles for quality review.
    """
    rows = (
        db.query(MechanicProfileRecord)
        .filter(
            MechanicProfileRecord.is_current.is_(True),
            MechanicProfileRecord.schema_version == PROFILE_SCHEMA_VERSION,
            MechanicProfileRecord.taxonomy_version == TAXONOMY_VERSION,
        )
        .order_by(MechanicProfileRecord.created_at.desc())
        .limit(n)
        .all()
    )
    return [
        {
            "name": record.oracle.name,
            "type_line": record.oracle.type_line,
            "oracle_text": record.oracle.oracle_text,
            "keywords": json.loads(record.oracle.keywords or "[]"),
            "profile": profile_from_record(record).model_dump(mode="json"),
            "provider": record.provider,
            "model": record.model,
            "created_at": record.created_at.isoformat(),
        }
        for record in rows
    ]


@app.get("/api/evaluations/mtg-quality")
def mtg_quality_evaluation(db: Annotated[Session, Depends(get_db)]):
    """Run the versioned MTG quality gate locally without provider requests."""
    return run_local_quality_evaluation(db)


# ══════════════════════════════════════════════════════════════════════════════
# Deckbuilding endpoints
# ══════════════════════════════════════════════════════════════════════════════

_QTY_NAME_RE = re.compile(r"^(\d+)\s+(.+)$")


def _build_candidate_pool(
    db: Session,
    query: str | list[str],
    exclude_names: set[str] | None = None,
    *,
    seed_names: set[str] | None = None,
    commander_name: str | None = None,
    limit: int = 200,
) -> list[dict]:
    query_text = " ".join(query) if isinstance(query, list) else query
    return retrieve_owned_candidates(
        db,
        query_text,
        seed_names=seed_names,
        commander_name=commander_name,
        exclude_names=exclude_names,
        limit=limit,
    )


def _validate_decklist(db: Session, decklist_text: str) -> list[str]:
    """
    Deterministic checks for a pasted or externally generated decklist.
    Returns a list of warning strings (empty = clean).
    """
    warnings: list[str] = []
    lines = [l.strip() for l in decklist_text.strip().splitlines() if l.strip()]

    parsed: list[tuple[int, str]] = []
    for line in lines:
        m = _QTY_NAME_RE.match(line)
        if m:
            parsed.append((int(m.group(1)), m.group(2).strip()))

    total = sum(q for q, _ in parsed)
    if total != 100:
        warnings.append(f"Deck has {total} cards — Commander requires exactly 100.")

    name_counts: Counter = Counter(n.lower() for _, n in parsed)
    dups = [n for n, c in name_counts.items() if c > 1 and "basic" not in n]
    if dups:
        warnings.append(f"Non-basic duplicates found: {', '.join(dups[:5])}")

    all_names = [n for _, n in parsed]
    db_map = {
        c.name.lower(): c
        for c in db.query(CardPrinting).join(OracleCard).filter(OracleCard.name.in_(all_names)).all()
    }
    owned_oracle_ids = {
        row[0]
        for row in (
            db.query(CardPrinting.oracle_id)
            .join(InventoryLine, InventoryLine.scryfall_id == CardPrinting.scryfall_id)
            .distinct()
            .all()
        )
    }

    not_found  = []
    not_legal  = []
    not_owned  = []
    land_total = 0

    for qty, name in parsed:
        nl = name.lower()
        if "basic land" in nl or any(
            bl in nl for bl in ("plains", "island", "swamp", "mountain", "forest")
        ):
            land_total += qty
            continue
        card = db_map.get(nl)
        if not card:
            not_found.append(name)
            continue
        if card.legalities_json:
            leg = json.loads(card.legalities_json)
            if leg.get("commander") != "legal":
                not_legal.append(name)
        if card.oracle_id not in owned_oracle_ids:
            not_owned.append(name)
        if card.type_line and "land" in card.type_line.lower():
            land_total += qty

    if not_found:
        warnings.append(f"Cards not found in local DB: {', '.join(not_found[:5])}")
    if not_legal:
        warnings.append(f"Not Commander-legal: {', '.join(not_legal[:5])}")
    if not_owned:
        warnings.append(f"Not in your collection: {', '.join(not_owned[:5])}")
    if land_total < 16:
        warnings.append(f"Low land count ({land_total}) — Commander decks typically need 35–38.")
    elif land_total > 42:
        warnings.append(f"High land count ({land_total}) — may want to cut some.")

    return warnings


def _parse_existing_deck_names(decklist_text: str) -> set[str]:
    return {name.casefold() for name in parse_deck_names(decklist_text)}


def _existing_deck_context(db: Session, decklist_text: str) -> list[dict]:
    """Resolve pasted names against local Oracle cards, including Moxfield suffixes."""
    oracle_cards = db.query(OracleCard).all()
    canonical = {card.name.casefold(): card for card in oracle_cards}
    ordered_names = sorted(canonical, key=len, reverse=True)
    quantities: Counter[str] = Counter()
    for quantity, raw_name in parse_deck_entries(decklist_text):
        normalized = raw_name.casefold()
        card = canonical.get(normalized)
        if card is None:
            match = next(
                (name for name in ordered_names if normalized.startswith(name + " (") or normalized.startswith(name + " [")),
                None,
            )
            card = canonical.get(match) if match else None
        if card is None:
            continue
        quantities[card.oracle_id] += quantity
    by_id = {card.oracle_id: card for card in oracle_cards}
    return [
        {
            "oracle_id": oracle_id,
            "name": by_id[oracle_id].name,
            "quantity": quantity,
            "cmc": by_id[oracle_id].cmc,
            "type_line": by_id[oracle_id].type_line,
            "oracle_text": by_id[oracle_id].oracle_text,
            "deterministic_roles": sorted(deterministic_roles(by_id[oracle_id])),
        }
        for oracle_id, quantity in quantities.items()
    ]


class _BuildRequest(BaseModel):
    theme: str = Field(min_length=1, max_length=2_000)
    commander_name: str | None = Field(default=None, max_length=500)


class _SuggestRequest(BaseModel):
    current_list: str = Field(min_length=1, max_length=settings.max_ai_text_chars)
    theme_hint: str | None = Field(default=None, max_length=2_000)


class _AuditRequest(BaseModel):
    decklist: str = Field(min_length=1, max_length=settings.max_ai_text_chars)


class _CandidateRequest(BaseModel):
    query: str = Field(default="", max_length=2_000)
    seed_names: list[str] = Field(default_factory=list, max_length=200)
    commander_name: str | None = Field(default=None, max_length=500)
    exclude_names: list[str] = Field(default_factory=list, max_length=200)
    limit: int = Field(default=100, ge=1, le=200)


class _DraftEntry(BaseModel):
    scryfall_id: str = Field(min_length=1, max_length=64)
    oracle_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=500)
    quantity: int = Field(ge=1, le=999)
    is_commander: bool = False


class _DraftRequest(BaseModel):
    entries: list[_DraftEntry] = Field(min_length=1, max_length=250)


class _SaveRecommendationRequest(_DraftRequest):
    deck_name: str = Field(min_length=1, max_length=200)
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=10_000)


class _RecommendationFeedbackRequest(_DraftRequest):
    outcome: str = Field(pattern="^(saved|edited|accepted|rejected)$")
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=10_000)


def _candidate_options(pool: list[dict]) -> list[dict]:
    return [
        {
            "scryfall_id": card["scryfall_id"],
            "oracle_id": card["oracle_id"],
            "name": card["name"],
            "mana_cost": card.get("mana_cost"),
            "cmc": card.get("cmc"),
            "type_line": card.get("type_line"),
            "color_identity": card.get("color_identity"),
            "owned_quantity": card.get("owned_quantity", 0),
            "deterministic_roles": card.get("deterministic_roles", []),
            "structured_roles": (card.get("mechanic_profile") or {}).get("roles", []),
            "retrieval": card.get("retrieval", {}),
        }
        for card in pool
    ]


def _require_recommendation_run(db: Session, run_id: str) -> RecommendationRun:
    run = db.get(RecommendationRun, run_id)
    if run is None:
        raise HTTPException(404, detail="Recommendation run not found")
    return run


@app.post("/api/deckbuilding/candidates")
def deckbuilding_candidates(body: _CandidateRequest, db: Annotated[Session, Depends(get_db)]):
    """Return owned candidates with deterministic, transparent relevance scores."""
    pool = _build_candidate_pool(
        db,
        body.query,
        seed_names=set(body.seed_names),
        commander_name=body.commander_name,
        exclude_names=set(body.exclude_names),
        limit=body.limit,
    )
    return {"pool_size": len(pool), "retrieval": public_score_summary(pool, body.limit)}


@app.post("/api/deckbuilding/build")
def deckbuilding_build(body: _BuildRequest, db: Annotated[Session, Depends(get_db)]):
    """Reason about packages, then deterministically build from owned legal cards."""
    seeds = {body.commander_name} if body.commander_name else set()
    pool = _build_candidate_pool(
        db, body.theme, seed_names=seeds, commander_name=body.commander_name
    )

    _log.info("Deckbuilding/build theme=%r pool_size=%s", body.theme, len(pool))

    if not pool:
        raise HTTPException(400, detail="No owned legal candidates matched the request")
    reasoner = build_strategy_reasoner()
    pipeline = build_deck_with_reasoning(
        db,
        theme=body.theme,
        candidates=pool,
        commander_name=body.commander_name,
        reasoner=reasoner,
    )
    provenance = pipeline["result"]["reasoning_provenance"]
    run = create_recommendation_run(
        db,
        query_text=body.theme,
        requested_commander=body.commander_name,
        provider=provenance["provider"],
        model=provenance["model"],
        proposal=pipeline["result"]["reasoning_proposal"],
        optimizer=pipeline["result"]["optimizer"],
        candidates=pool,
    )
    db.commit()

    return {
        **pipeline,
        "recommendation_run_id": run.id,
        "pool_size": len(pool),
        "retrieval": public_score_summary(pool),
        "candidate_options": _candidate_options(pool),
    }


@app.post("/api/deckbuilding/recommendations/{run_id}/validate")
def validate_recommendation_draft(
    run_id: str,
    body: _DraftRequest,
    db: Annotated[Session, Depends(get_db)],
):
    run = _require_recommendation_run(db, run_id)
    candidates = candidates_for_run(run)
    entries = [entry.model_dump() for entry in body.entries]
    validation = validate_optimized_deck(db, candidates, entries)
    return {"validation": validation, "decklist": format_decklist(entries)}


@app.post("/api/deckbuilding/recommendations/{run_id}/save")
def save_recommendation_draft(
    run_id: str,
    body: _SaveRecommendationRequest,
    db: Annotated[Session, Depends(get_db)],
):
    run = _require_recommendation_run(db, run_id)
    candidates = candidates_for_run(run)
    entries = [entry.model_dump() for entry in body.entries]
    validation = validate_optimized_deck(db, candidates, entries)
    if not validation["valid"]:
        raise HTTPException(400, detail={
            "message": "Edited deck failed hard constraints",
            "validation": validation,
        })

    commander = next(entry for entry in entries if entry["is_commander"])
    deck = Deck(
        name=body.deck_name.strip(),
        format="commander",
        status="building",
        notes=f"Created from recommendation run {run.id}",
        commander_scryfall_id=commander["scryfall_id"],
        commander_oracle_id=commander["oracle_id"],
    )
    db.add(deck)
    db.flush()
    for entry in entries:
        _merge_deck_card(
            db,
            deck.id,
            entry["scryfall_id"],
            entry["quantity"],
            is_commander=entry["is_commander"],
            is_sideboard=False,
        )
    feedback = record_recommendation_feedback(
        db,
        run=run,
        outcome="saved",
        rating=body.rating,
        notes=body.notes or "Saved as a deck from the recommendation workspace.",
        edited_entries=entries,
        saved_deck_id=deck.id,
    )
    db.commit()
    return {
        "deck": get_deck(deck.id, db),
        "validation": validation,
        "feedback_id": feedback.id,
    }


@app.post("/api/deckbuilding/recommendations/{run_id}/feedback")
def submit_recommendation_feedback(
    run_id: str,
    body: _RecommendationFeedbackRequest,
    db: Annotated[Session, Depends(get_db)],
):
    run = _require_recommendation_run(db, run_id)
    candidates = candidates_for_run(run)
    allowed_ids = {card["oracle_id"] for card in candidates}
    entries = [entry.model_dump() for entry in body.entries]
    if any(entry["oracle_id"] not in allowed_ids for entry in entries):
        raise HTTPException(400, detail="Feedback contains a card outside the recommendation pool")
    feedback = record_recommendation_feedback(
        db,
        run=run,
        outcome=body.outcome,
        rating=body.rating,
        notes=body.notes,
        edited_entries=entries,
    )
    db.commit()
    return {
        "feedback_id": feedback.id,
        "outcome": feedback.outcome,
        "added_or_increased": json.loads(feedback.added_or_increased_json),
        "removed_or_decreased": json.loads(feedback.removed_or_decreased_json),
    }


@app.post("/api/deckbuilding/suggest")
def deckbuilding_suggest(body: _SuggestRequest, db: Annotated[Session, Depends(get_db)]):
    """Suggest additions to an in-progress deck from owned cards."""
    existing_cards = _existing_deck_context(db, body.current_list)
    existing_names = {card["name"].casefold() for card in existing_cards}
    pool = _build_candidate_pool(
        db,
        body.theme_hint or "",
        seed_names=existing_names,
        exclude_names=existing_names,
    )

    _log.info("Deckbuilding/suggest pool_size=%s", len(pool))

    reviewer = build_deck_reviewer()
    result = reviewer.suggest(body.current_list, pool, body.theme_hint, existing_cards)
    return {
        "result": {
            **result.model_dump(mode="json"),
            "review_provenance": {
                "provider": reviewer.provider_name,
                "model": reviewer.model_name,
                "schema_version": result.schema_version,
            },
        },
        "warnings": [],
        "pool_size": len(pool),
        "retrieval": public_score_summary(pool),
    }


@app.post("/api/deckbuilding/audit")
def deckbuilding_audit(body: _AuditRequest, db: Annotated[Session, Depends(get_db)]):
    """Audit a complete deck and suggest improvements from owned cards."""
    existing_cards = _existing_deck_context(db, body.decklist)
    existing_names = {card["name"].casefold() for card in existing_cards}
    pool = _build_candidate_pool(
        db, "", seed_names=existing_names, exclude_names=existing_names
    )

    _log.info("Deckbuilding/audit pool_size=%s", len(pool))

    reviewer = build_deck_reviewer()
    result = reviewer.audit(body.decklist, pool, existing_cards)
    return {
        "result": {
            **result.model_dump(mode="json"),
            "review_provenance": {
                "provider": reviewer.provider_name,
                "model": reviewer.model_name,
                "schema_version": result.schema_version,
            },
        },
        "warnings": _validate_decklist(db, body.decklist),
        "pool_size": len(pool),
        "retrieval": public_score_summary(pool),
    }
