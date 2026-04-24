import json
import random
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CardCache

# Scryfall asks for ≥50–100 ms between requests and a descriptive User-Agent.
_USER_AGENT = "Spellbinder-MTG-Inventory/0.1 (homelab; github.com/spellbinder)"
_REQUEST_HEADERS = {"User-Agent": _USER_AGENT}
_MIN_INTERVAL = 0.1  # seconds between requests
_MAX_RETRIES = 6     # attempts before giving up on a 429
_BACKOFF_BASE = 2.0  # seconds for first retry; doubles each attempt


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


def image_uri_normal_from_payload(data: dict) -> str | None:
    img = data.get("image_uris") or {}
    if not img and data.get("card_faces"):
        img = (data["card_faces"][0] or {}).get("image_uris") or {}
    return img.get("normal")


class ScryfallClient:
    def __init__(self):
        self.base = settings.scryfall_base.rstrip("/")

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Rate-limited request with exponential backoff on 429."""
        for attempt in range(_MAX_RETRIES):
            _limiter.wait()
            with httpx.Client(timeout=30.0, headers=_REQUEST_HEADERS) as client:
                r = client.request(method, url, **kwargs)
            if r.status_code != 429:
                return r
            retry_after = float(r.headers.get("Retry-After", _BACKOFF_BASE * (2 ** attempt)))
            time.sleep(retry_after + random.uniform(0, 1.0))
        r.raise_for_status()
        return r

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

    def upsert_cache_from_scryfall(self, db: Session, data: dict, *, commit: bool = True) -> CardCache:
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

        row = db.get(CardCache, sf_id)
        if row is None:
            row = CardCache(scryfall_id=sf_id)
            db.add(row)

        row.oracle_id = data.get("oracle_id") or sf_id
        row.name = data.get("name") or "Unknown"
        row.type_line = data.get("type_line")
        row.oracle_text = data.get("oracle_text")
        if data.get("card_faces") and not row.oracle_text:
            parts = []
            for f in data["card_faces"]:
                if f.get("oracle_text"):
                    parts.append(f["oracle_text"])
            row.oracle_text = "\n".join(parts) if parts else None
        row.mana_cost = data.get("mana_cost")
        row.cmc = float(data.get("cmc") or 0)
        row.colors = colors
        row.color_identity = ci
        row.rarity = data.get("rarity")
        row.image_uri_normal = image_uri
        row.legalities_json = legalities
        row.scryfall_json = json.dumps(data)
        row.updated_at = datetime.utcnow()
        if commit:
            db.commit()
            db.refresh(row)
        return row


def ensure_card_cached(db: Session, scryfall_id: str) -> CardCache | None:
    row = db.get(CardCache, scryfall_id)
    if row and row.updated_at and datetime.utcnow() - row.updated_at < timedelta(days=14):
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
) -> dict[str, CardCache]:
    """
    Ensure all given IDs are in the local cache. Uses /cards/collection (75 per request)
    instead of one request per card, then commits once at the end.
    Returns a {scryfall_id: CardCache} map for every ID that Scryfall knows about.
    """
    if not scryfall_ids:
        return {}

    unique_ids = list(dict.fromkeys(scryfall_ids))  # deduplicate, preserve order

    cutoff = datetime.utcnow() - timedelta(days=14)
    fresh_rows = (
        db.query(CardCache)
        .filter(CardCache.scryfall_id.in_(unique_ids), CardCache.updated_at >= cutoff)
        .all()
    )
    cache_map: dict[str, CardCache] = {r.scryfall_id: r for r in fresh_rows}

    to_fetch = [sid for sid in unique_ids if sid not in cache_map]
    if not to_fetch:
        return cache_map

    client = ScryfallClient()
    batch_size = 75
    total_batches = (len(to_fetch) + batch_size - 1) // batch_size
    if progress_callback:
        progress_callback(0, total_batches)
    for i in range(0, len(to_fetch), batch_size):
        batch = to_fetch[i : i + batch_size]
        found, _ = client.fetch_cards_collection(batch)
        for data in found:
            row = client.upsert_cache_from_scryfall(db, data, commit=False)
            cache_map[row.scryfall_id] = row
        if progress_callback:
            progress_callback(i // batch_size + 1, total_batches)
    db.commit()

    return cache_map
