import json
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.logging_setup import get_logger
from app.models import CardPrinting, OracleCard

# Scryfall asks for ≥50–100 ms between requests and a descriptive User-Agent.
_USER_AGENT = "Spellbinder-MTG-Inventory/0.1 (homelab; github.com/spellbinder)"
_REQUEST_HEADERS = {"User-Agent": _USER_AGENT}
_MIN_INTERVAL = 0.1  # seconds between requests
_MAX_RETRIES = 6     # attempts before giving up on a 429
_BACKOFF_BASE = 2.0  # seconds for first retry; doubles each attempt
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_log = get_logger(".scryfall")


class _RateLimiter:
    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._last: float = 0.0

    def wait(self) -> None:
        with self._lock:
            gap = self._interval - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()


_limiter = _RateLimiter(_MIN_INTERVAL)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def image_uri_normal_from_payload(data: dict) -> str | None:
    img = data.get("image_uris") or {}
    if not img and data.get("card_faces"):
        img = (data["card_faces"][0] or {}).get("image_uris") or {}
    return img.get("normal")


class ScryfallClient:
    def __init__(self):
        self.base = settings.scryfall_base.rstrip("/")

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Rate-limited request with bounded retries for transient failures."""
        last_response: httpx.Response | None = None
        last_error: httpx.TransportError | None = None
        for attempt in range(_MAX_RETRIES):
            _limiter.wait()
            try:
                with httpx.Client(timeout=30.0, headers=_REQUEST_HEADERS) as client:
                    response = client.request(method, url, **kwargs)
                last_response = response
                if response.status_code not in _RETRYABLE_STATUSES:
                    return response
                retry_header = response.headers.get("Retry-After")
                try:
                    delay = float(retry_header) if retry_header else _BACKOFF_BASE * (2 ** attempt)
                except ValueError:
                    delay = _BACKOFF_BASE * (2 ** attempt)
                reason = f"HTTP {response.status_code}"
            except httpx.TransportError as exc:
                last_error = exc
                delay = _BACKOFF_BASE * (2 ** attempt)
                reason = f"{type(exc).__name__}: {exc}"

            if attempt + 1 >= _MAX_RETRIES:
                break
            delay = min(delay, 120.0) + random.uniform(0, 1.0)
            _log.warning(
                "Scryfall transient failure method=%s attempt=%d/%d retry_in=%.1fs reason=%s",
                method,
                attempt + 1,
                _MAX_RETRIES,
                delay,
                reason,
            )
            time.sleep(delay)

        _log.error(
            "Scryfall request exhausted retries method=%s attempts=%d last_status=%s last_error=%r",
            method,
            _MAX_RETRIES,
            last_response.status_code if last_response is not None else None,
            last_error,
        )
        if last_response is not None:
            last_response.raise_for_status()
        if last_error is not None:
            raise last_error
        raise RuntimeError("Scryfall request failed without a response")

    def fetch_card_by_id(self, scryfall_id: str) -> dict | None:
        r = self._request("GET", f"{self.base}/cards/{scryfall_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def fetch_named(self, name: str, *, exact: bool = True) -> dict | None:
        param = "exact" if exact else "fuzzy"
        r = self._request("GET", f"{self.base}/cards/named", params={param: name})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def fetch_cards_collection(self, scryfall_ids: list[str]) -> tuple[list[dict], list[str]]:
        """Fetch up to 75 cards by ID using the /cards/collection bulk endpoint."""
        identifiers = [{"id": sid} for sid in scryfall_ids]
        r = self._request("POST", f"{self.base}/cards/collection", json={"identifiers": identifiers})
        r.raise_for_status()
        data = r.json()
        found = data.get("data") or []
        not_found_ids = [
            item.get("id") for item in (data.get("not_found") or []) if item.get("id")
        ]
        return found, not_found_ids

    def fetch_cards_collection_by_name(self, names: list[str]) -> tuple[list[dict], list[str]]:
        """Fetch up to 75 cards by name using the /cards/collection bulk endpoint."""
        identifiers = [{"name": n} for n in names]
        r = self._request("POST", f"{self.base}/cards/collection", json={"identifiers": identifiers})
        r.raise_for_status()
        data = r.json()
        found = data.get("data") or []
        not_found = [
            item.get("name") for item in (data.get("not_found") or []) if item.get("name")
        ]
        return found, not_found

    def fetch_cards_collection_by_printing(
        self, printings: list[tuple[str, str]]
    ) -> tuple[list[dict], list[tuple[str, str]]]:
        """Fetch up to 75 exact set/collector-number printings."""
        identifiers = [
            {"set": set_code.lower(), "collector_number": collector_number}
            for set_code, collector_number in printings
        ]
        r = self._request("POST", f"{self.base}/cards/collection", json={"identifiers": identifiers})
        r.raise_for_status()
        data = r.json()
        found = data.get("data") or []
        not_found = [
            (str(item.get("set") or ""), str(item.get("collector_number") or ""))
            for item in (data.get("not_found") or [])
        ]
        return found, not_found

    def search_cards(self, query: str, *, limit: int = 12) -> list[dict]:
        r = self._request(
            "GET", f"{self.base}/cards/search",
            params={"q": query, "unique": "cards", "order": "name", "dir": "asc"},
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        return list((data.get("data") or [])[:limit])

    def upsert_cache_from_scryfall(self, db: Session, data: dict, *, commit: bool = True) -> CardPrinting:
        sf_id = data.get("id")
        if not sf_id:
            raise ValueError("Scryfall payload missing id")

        image_uri = image_uri_normal_from_payload(data)

        def _merged_colors() -> list[str]:
            c = list(data.get("colors") or [])
            if c:
                return sorted(c)
            acc: set[str] = set()
            for f in data.get("card_faces") or []:
                acc.update(f.get("colors") or [])
            return sorted(acc)

        def _merged_color_identity() -> list[str]:
            ci = list(data.get("color_identity") or [])
            if ci:
                return sorted(ci)
            acc: set[str] = set()
            for f in data.get("card_faces") or []:
                acc.update(f.get("color_identity") or [])
            return sorted(acc)

        colors = ",".join(_merged_colors())
        ci = ",".join(_merged_color_identity())

        legalities = json.dumps(data.get("legalities") or {})

        oracle_id = data.get("oracle_id") or sf_id
        oracle = db.get(OracleCard, oracle_id)
        if oracle is None:
            # Session.get() cannot see a new object until it has been flushed.
            # Scryfall collection batches can contain multiple printings of one
            # Oracle card, so reuse the pending object instead of inserting the
            # same primary key twice when the batch commits.
            oracle = next(
                (
                    pending
                    for pending in db.new
                    if isinstance(pending, OracleCard)
                    and pending.oracle_id == oracle_id
                ),
                None,
            )
        if oracle is None:
            oracle = OracleCard(oracle_id=oracle_id, name=data.get("name") or "Unknown")
            db.add(oracle)

        oracle.name = data.get("name") or "Unknown"
        oracle.type_line = data.get("type_line")
        oracle.oracle_text = data.get("oracle_text")
        if data.get("card_faces") and not oracle.oracle_text:
            parts = []
            for f in data["card_faces"]:
                if f.get("oracle_text"):
                    parts.append(f["oracle_text"])
            oracle.oracle_text = "\n".join(parts) if parts else None
        oracle.mana_cost = data.get("mana_cost")
        oracle.cmc = float(data.get("cmc") or 0)
        oracle.colors = colors
        oracle.color_identity = ci
        oracle.legalities_json = legalities
        oracle.keywords = json.dumps(data.get("keywords") or [])
        oracle.updated_at = _utcnow()

        row = db.get(CardPrinting, sf_id)
        if row is None:
            row = CardPrinting(scryfall_id=sf_id, oracle_id=oracle_id)
            db.add(row)
        row.oracle = oracle
        row.set_code = data.get("set")
        row.collector_number = data.get("collector_number")
        row.rarity = data.get("rarity")
        row.language = data.get("lang")
        row.image_uri_normal = image_uri
        row.scryfall_json = json.dumps(data)
        row.updated_at = _utcnow()
        if commit:
            db.commit()
            db.refresh(row)
        return row


def ensure_card_cached(db: Session, scryfall_id: str) -> CardPrinting | None:
    row = db.get(CardPrinting, scryfall_id)
    if row and row.updated_at and _utcnow() - row.updated_at < timedelta(days=14):
        return row

    client = ScryfallClient()
    data = client.fetch_card_by_id(scryfall_id)
    if not data:
        return None
    return client.upsert_cache_from_scryfall(db, data)


def bulk_ensure_cards_cached(
    db: Session,
    scryfall_ids: list[str],
    progress_callback: Callable[[int, int], None] | None = None,
    *,
    refresh_stale: bool = True,
) -> dict[str, CardPrinting]:
    """
    Ensure all given IDs are in the local cache. Uses /cards/collection (75 per request)
    instead of one request per card. Each cache batch is committed independently
    so a later transient failure can resume without downloading prior batches.
    Returns a {scryfall_id: CardPrinting} map for every ID that Scryfall knows about.
    """
    if not scryfall_ids:
        return {}

    unique_ids = list(dict.fromkeys(scryfall_ids))  # deduplicate, preserve order

    cached_query = db.query(CardPrinting).filter(CardPrinting.scryfall_id.in_(unique_ids))
    if refresh_stale:
        cached_query = cached_query.filter(
            CardPrinting.updated_at >= _utcnow() - timedelta(days=14)
        )
    cached_rows = cached_query.all()
    cache_map: dict[str, CardPrinting] = {r.scryfall_id: r for r in cached_rows}

    to_fetch = [sid for sid in unique_ids if sid not in cache_map]
    if not to_fetch:
        _log.info(
            "Scryfall cache hydration skipped requested=%d cached=%d refresh_stale=%s",
            len(unique_ids),
            len(cache_map),
            refresh_stale,
        )
        return cache_map

    client = ScryfallClient()
    batch_size = 75
    total_batches = (len(to_fetch) + batch_size - 1) // batch_size
    _log.info(
        "Scryfall cache hydration requested=%d cached=%d fetching=%d batches=%d refresh_stale=%s",
        len(unique_ids),
        len(cache_map),
        len(to_fetch),
        total_batches,
        refresh_stale,
    )
    if progress_callback:
        progress_callback(0, total_batches)
    for i in range(0, len(to_fetch), batch_size):
        batch = to_fetch[i : i + batch_size]
        batch_number = i // batch_size + 1
        started_at = time.monotonic()
        found, not_found = client.fetch_cards_collection(batch)
        for data in found:
            row = client.upsert_cache_from_scryfall(db, data, commit=False)
            cache_map[row.scryfall_id] = row
        db.commit()
        _log.debug(
            "Scryfall cache batch committed batch=%d/%d requested=%d found=%d not_found=%d elapsed=%.2fs",
            batch_number,
            total_batches,
            len(batch),
            len(found),
            len(not_found),
            time.monotonic() - started_at,
        )
        if progress_callback:
            progress_callback(batch_number, total_batches)

    return cache_map


def bulk_ensure_cards_cached_by_name(
    db: Session,
    names: list[str],
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, CardPrinting]:
    """
    Resolve card names → CardPrinting rows using /cards/collection name identifiers
    (75 per request). Returns {name.lower(): CardPrinting}. Names Scryfall doesn't
    recognise are silently omitted; callers should fall back to individual lookup.
    """
    if not names:
        return {}

    unique_names = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    cutoff = _utcnow() - timedelta(days=14)

    fresh_rows = (
        db.query(CardPrinting)
        .join(OracleCard)
        .filter(OracleCard.name.in_(unique_names), CardPrinting.updated_at >= cutoff)
        .all()
    )
    name_map: dict[str, CardPrinting] = {r.name.lower(): r for r in fresh_rows}

    to_fetch = [n for n in unique_names if n.lower() not in name_map]
    if not to_fetch:
        return name_map

    client = ScryfallClient()
    batch_size = 75
    total_batches = (len(to_fetch) + batch_size - 1) // batch_size
    if progress_callback:
        progress_callback(0, total_batches)
    for i in range(0, len(to_fetch), batch_size):
        batch = to_fetch[i : i + batch_size]
        found, _ = client.fetch_cards_collection_by_name(batch)
        for data in found:
            row = client.upsert_cache_from_scryfall(db, data, commit=False)
            name_map[row.name.lower()] = row
        if progress_callback:
            progress_callback(i // batch_size + 1, total_batches)
    db.commit()

    return name_map


def bulk_ensure_cards_cached_by_printing(
    db: Session,
    printings: list[tuple[str, str]],
) -> dict[tuple[str, str], CardPrinting]:
    """Resolve exact `(set, collector_number)` identifiers in bulk."""
    unique_printings = list(dict.fromkeys(
        (set_code.strip().lower(), collector_number.strip().lower())
        for set_code, collector_number in printings
        if set_code.strip() and collector_number.strip()
    ))
    if not unique_printings:
        return {}

    set_codes = {set_code for set_code, _ in unique_printings}
    local_rows = (
        db.query(CardPrinting)
        .filter(CardPrinting.set_code.in_(set_codes))
        .all()
    )
    result = {
        ((row.set_code or "").lower(), (row.collector_number or "").lower()): row
        for row in local_rows
        if row.set_code and row.collector_number
    }
    to_fetch = [printing for printing in unique_printings if printing not in result]
    if not to_fetch:
        return result

    client = ScryfallClient()
    for index in range(0, len(to_fetch), 75):
        found, _ = client.fetch_cards_collection_by_printing(to_fetch[index:index + 75])
        for data in found:
            row = client.upsert_cache_from_scryfall(db, data, commit=False)
            if row.set_code and row.collector_number:
                result[(row.set_code.lower(), row.collector_number.lower())] = row
    db.commit()
    return result
