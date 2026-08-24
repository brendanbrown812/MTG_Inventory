"""Deterministic Commander legality, availability, and deck-health analysis.

This module intentionally makes no network or AI calls. Formal Commander
rules and advisory deck-health heuristics are reported separately.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CardPrinting, Deck, InventoryLine, OracleCard


COLORS = ("W", "U", "B", "R", "G")
BASIC_LAND_TYPES = {
    "plains": "W",
    "island": "U",
    "swamp": "B",
    "mountain": "R",
    "forest": "G",
    "wastes": "C",
}

LAND_TARGET = (35, 40)
MANA_SOURCE_MIN = 38
AVERAGE_MV_MAX = 4.0
HIGH_MV_MAX = 15

ROLE_TARGETS: dict[str, tuple[int, int]] = {
    "ramp": (8, 12),
    "card_draw": (8, 12),
    "spot_removal": (6, 10),
    "board_wipes": (2, 4),
    "protection": (2, 5),
    "recursion": (2, 5),
    "graveyard_hate": (1, 3),
    "counterspells": (0, 4),
    "tutors": (0, 4),
}

ROLE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "card_draw": (
        re.compile(r"\bdraw (?:a|one|two|three|four|five|x|that many|\d+) cards?\b"),
        re.compile(r"\bdraw cards? equal to\b"),
    ),
    "spot_removal": (
        re.compile(
            r"\b(?:destroy|exile) target (?:artifact|creature|enchantment|land|"
            r"nonland permanent|permanent|planeswalker)\b"
        ),
        re.compile(r"\breturn target (?:nonland )?permanent\b.*\bto (?:its|their) owner'?s hand\b"),
        re.compile(r"\bdeals? \d+ damage to (?:any|another|target) target\b"),
        re.compile(r"\btarget creature gets -\d+/-\d+\b"),
    ),
    "board_wipes": (
        re.compile(r"\b(?:destroy|exile) all (?:creatures|nonland permanents|permanents)\b"),
        re.compile(r"\ball creatures get -\d+/-\d+\b"),
        re.compile(r"\bdeals? \d+ damage to each creature\b"),
        re.compile(r"\beach player sacrifices all creatures\b"),
    ),
    "counterspells": (re.compile(r"\bcounter target (?:spell|activated ability|triggered ability)\b"),),
    "protection": (
        re.compile(r"\b(?:hexproof|indestructible|protection from|phasing)\b"),
        re.compile(r"\bregenerate target\b"),
    ),
    "recursion": (
        re.compile(r"\breturn target .* card from your graveyard\b"),
        re.compile(r"\bput target .* card from (?:a|your) graveyard onto the battlefield\b"),
        re.compile(r"\byou may cast .* from your graveyard\b"),
    ),
    "graveyard_hate": (
        re.compile(r"\bexile (?:all cards|target card|up to .* cards?) from .* graveyard\b"),
        re.compile(r"\bcards? in graveyards? can'?t\b"),
    ),
    "tutors": (
        re.compile(r"\bsearch your library for (?:a|an|up to one|two) (?!basic land|land card)"),
    ),
}

_DIRECT_MANA_RE = re.compile(r"\badd\b[^.\n]*?(\{[WUBRGC](?:/[WUBRGC])?\})", re.I)
_ANY_COLOR_RE = re.compile(r"\badd (?:one mana of )?any color\b", re.I)
_COMMANDER_COLOR_RE = re.compile(r"\badd one mana of any color in your commander'?s color identity\b", re.I)
_RAMP_PATTERNS = (
    re.compile(r"\bsearch your library for (?:a|an|up to one|two) .*land card.*onto the battlefield\b"),
    re.compile(r"\bput (?:a|an|up to one|two) .*land card.*onto the battlefield\b"),
    re.compile(r"\bcreate (?:a|one|two|\d+) treasure tokens?\b"),
)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}
_LIMITED_SINGLETON_RE = re.compile(
    r"a deck can have up to ([a-z]+|\d+) cards named ", re.I
)


@dataclass
class _Entry:
    oracle: OracleCard
    printing: CardPrinting
    quantity: int
    is_commander: bool


def _finding(code: str, severity: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "details": details}


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _json_array(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _color_set(raw: str | None) -> set[str]:
    return {part.strip().upper() for part in (raw or "").split(",") if part.strip()}


def _is_land(card: OracleCard) -> bool:
    return "land" in (card.type_line or "").lower()


def _is_basic_land(card: OracleCard) -> bool:
    type_line = (card.type_line or "").lower()
    return "basic" in type_line and "land" in type_line


def _singleton_limit(card: OracleCard) -> int | None:
    """Return None for unlimited, otherwise the maximum legal copies."""
    if _is_basic_land(card):
        return None
    text = card.oracle_text or ""
    if re.search(r"a deck can have any number of cards named ", text, re.I):
        return None
    match = _LIMITED_SINGLETON_RE.search(text)
    if match:
        token = match.group(1).lower()
        return int(token) if token.isdigit() else _NUMBER_WORDS.get(token, 1)
    return 1


def singleton_limit(card: OracleCard) -> int | None:
    """Public Commander copy limit used by deck assembly and validation."""
    return _singleton_limit(card)


def _printed_power_toughness(printing: CardPrinting) -> bool:
    payload = _json_object(printing.scryfall_json)
    if payload.get("power") is not None and payload.get("toughness") is not None:
        return True
    return any(
        isinstance(face, dict)
        and face.get("power") is not None
        and face.get("toughness") is not None
        for face in payload.get("card_faces") or []
    )


def commander_eligibility(printing: CardPrinting) -> tuple[bool, str]:
    card = printing.oracle
    type_line = (card.type_line or "").lower()
    oracle_text = (card.oracle_text or "").lower()
    if "can be your commander" in oracle_text:
        return True, "rules text explicitly allows this card to be a commander"
    if "legendary" in type_line and "creature" in type_line:
        return True, "legendary creature"
    if (
        "legendary" in type_line
        and ("vehicle" in type_line or "spacecraft" in type_line)
        and _printed_power_toughness(printing)
    ):
        return True, "legendary Vehicle or Spacecraft with printed power/toughness"
    return False, "not a legendary creature or another permitted commander card"


def _partner_compatible(commanders: list[_Entry]) -> bool:
    if len(commanders) != 2:
        return len(commanders) == 1
    first, second = commanders
    first_text = (first.oracle.oracle_text or "").lower()
    second_text = (second.oracle.oracle_text or "").lower()
    first_keywords = {str(k).lower() for k in _json_array(first.oracle.keywords)}
    second_keywords = {str(k).lower() for k in _json_array(second.oracle.keywords)}

    if "partner" in first_keywords and "partner" in second_keywords:
        return True
    if "friends forever" in first_text and "friends forever" in second_text:
        return True
    if "partner with " in first_text and second.oracle.name.lower() in first_text:
        return "partner with " in second_text and first.oracle.name.lower() in second_text
    if "choose a background" in first_text and "background" in (second.oracle.type_line or "").lower():
        return True
    if "choose a background" in second_text and "background" in (first.oracle.type_line or "").lower():
        return True
    if "doctor's companion" in first_text and "time lord doctor" in (second.oracle.type_line or "").lower():
        return True
    if "doctor's companion" in second_text and "time lord doctor" in (first.oracle.type_line or "").lower():
        return True
    return False


def _background_pair_allows(entry: _Entry, commanders: list[_Entry]) -> bool:
    if "background" not in (entry.oracle.type_line or "").lower():
        return False
    return any(
        other is not entry and "choose a background" in (other.oracle.oracle_text or "").lower()
        for other in commanders
    )


def _role_set(card: OracleCard) -> set[str]:
    text = (card.oracle_text or "").lower()
    roles = {
        role
        for role, patterns in ROLE_PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    }
    if not _is_land(card) and (
        _DIRECT_MANA_RE.search(text)
        or _ANY_COLOR_RE.search(text)
        or any(pattern.search(text) for pattern in _RAMP_PATTERNS)
    ):
        roles.add("ramp")
    return roles


def deterministic_roles(card: OracleCard) -> set[str]:
    """Public, deterministic functional-role classification for shared consumers."""
    return _role_set(card)


def _produced_colors(entry: _Entry, commander_colors: set[str]) -> set[str]:
    payload = _json_object(entry.printing.scryfall_json)
    produced = {str(c).upper() for c in payload.get("produced_mana") or []}
    if produced:
        return produced

    text = entry.oracle.oracle_text or ""
    type_line = (entry.oracle.type_line or "").lower()
    inferred: set[str] = set()
    if _is_land(entry.oracle):
        for land_type, color in BASIC_LAND_TYPES.items():
            if land_type in type_line:
                inferred.add(color)
        lower_text = text.lower()
        if "search your library" in lower_text and "land" in lower_text:
            named_types = {
                color for land_type, color in BASIC_LAND_TYPES.items()
                if land_type != "wastes" and land_type in lower_text
            }
            inferred.update(named_types or commander_colors)
    for symbol in _DIRECT_MANA_RE.findall(text):
        inferred.update(c for c in symbol.upper() if c in "WUBRGC")
    if _COMMANDER_COLOR_RE.search(text):
        inferred.update(commander_colors)
    elif _ANY_COLOR_RE.search(text):
        inferred.update(COLORS)
    return inferred


def _mana_demand(entries: list[_Entry]) -> Counter[str]:
    demand: Counter[str] = Counter()
    for entry in entries:
        if _is_land(entry.oracle):
            continue
        cost = entry.oracle.mana_cost or ""
        for symbol in re.findall(r"\{([^{}]+)\}", cost):
            for color in COLORS:
                if color in symbol.upper():
                    demand[color] += entry.quantity
    return demand


def _curve(entries: list[_Entry]) -> dict[str, Any]:
    values: list[float] = []
    buckets = Counter({"0-1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7+": 0})
    for entry in entries:
        if _is_land(entry.oracle):
            continue
        mv = float(entry.oracle.cmc or 0)
        values.extend([mv] * entry.quantity)
        bucket = "0-1" if mv <= 1 else str(int(mv)) if mv <= 6 else "7+"
        buckets[bucket] += entry.quantity
    return {
        "average_mana_value": round(sum(values) / len(values), 2) if values else 0.0,
        "nonland_cards": len(values),
        "high_mana_value_cards": sum(1 for value in values if value >= 6),
        "buckets": dict(buckets),
    }


def analyze_commander_deck(db: Session, deck: Deck) -> dict[str, Any]:
    legality_findings: list[dict[str, Any]] = []
    health_findings: list[dict[str, Any]] = []

    active_cards = [dc for dc in deck.cards if not dc.is_sideboard]
    if any(dc.is_sideboard for dc in deck.cards):
        legality_findings.append(_finding(
            "sideboard_ignored", "warning",
            "Commander has no normal sideboard; sideboard entries were excluded from analysis.",
        ))

    entries_by_oracle: dict[str, _Entry] = {}
    flagged_commander_ids: set[str] = set()
    for dc in active_cards:
        if dc.quantity <= 0:
            legality_findings.append(_finding(
                "invalid_quantity", "error", f"{dc.oracle_card.name} has quantity {dc.quantity}.",
                oracle_id=dc.oracle_id, quantity=dc.quantity,
            ))
        if dc.is_commander:
            flagged_commander_ids.add(dc.oracle_id)
        existing = entries_by_oracle.get(dc.oracle_id)
        if existing:
            existing.quantity += dc.quantity
            existing.is_commander = existing.is_commander or dc.is_commander
        else:
            entries_by_oracle[dc.oracle_id] = _Entry(
                oracle=dc.oracle_card,
                printing=dc.card,
                quantity=dc.quantity,
                is_commander=dc.is_commander,
            )

    commander_ids = set(flagged_commander_ids)
    if deck.commander_oracle_id:
        commander_ids.add(deck.commander_oracle_id)
    elif deck.commander_scryfall_id:
        printing = db.get(CardPrinting, deck.commander_scryfall_id)
        if printing:
            commander_ids.add(printing.oracle_id)

    # A commander selected in deck settings counts as one of the 100 even if
    # the deck-card row has not been added yet.
    for oracle_id in commander_ids:
        if oracle_id not in entries_by_oracle:
            printing = None
            if deck.commander_scryfall_id:
                candidate = db.get(CardPrinting, deck.commander_scryfall_id)
                if candidate and candidate.oracle_id == oracle_id:
                    printing = candidate
            if printing is None:
                printing = db.query(CardPrinting).filter(CardPrinting.oracle_id == oracle_id).first()
            oracle = db.get(OracleCard, oracle_id)
            if printing and oracle:
                entries_by_oracle[oracle_id] = _Entry(oracle, printing, 1, True)

    entries = sorted(entries_by_oracle.values(), key=lambda entry: (entry.oracle.name, entry.oracle.oracle_id))
    commanders = sorted(
        (entry for entry in entries if entry.oracle.oracle_id in commander_ids),
        key=lambda entry: (entry.oracle.name, entry.oracle.oracle_id),
    )

    if not commanders:
        legality_findings.append(_finding(
            "missing_commander", "error", "The deck does not have a commander selected."
        ))
    elif len(commanders) > 2:
        legality_findings.append(_finding(
            "too_many_commanders", "error", "A Commander deck can have at most two commanders.",
            commanders=[entry.oracle.name for entry in commanders],
        ))
    else:
        for entry in commanders:
            eligible, reason = commander_eligibility(entry.printing)
            if not eligible and _background_pair_allows(entry, commanders):
                eligible, reason = True, "Background paired with a commander that has choose a Background"
            if not eligible:
                legality_findings.append(_finding(
                    "ineligible_commander", "error",
                    f"{entry.oracle.name} is not eligible to be a commander.",
                    card_name=entry.oracle.name, reason=reason,
                ))
        if len(commanders) == 2 and not _partner_compatible(commanders):
            legality_findings.append(_finding(
                "incompatible_commanders", "error",
                "The selected commanders do not have compatible partner-style abilities.",
                commanders=[entry.oracle.name for entry in commanders],
            ))

    commander_colors: set[str] = set()
    for entry in commanders:
        commander_colors.update(_color_set(entry.oracle.color_identity))

    deck_size = sum(max(0, entry.quantity) for entry in entries)
    if deck_size != 100:
        legality_findings.append(_finding(
            "deck_size", "error", f"Commander decks must contain exactly 100 cards; this deck has {deck_size}.",
            actual=deck_size, required=100, delta=deck_size - 100,
        ))

    name_quantities: Counter[str] = Counter()
    name_cards: dict[str, OracleCard] = {}
    for entry in entries:
        key = entry.oracle.name.casefold()
        name_quantities[key] += max(0, entry.quantity)
        name_cards[key] = entry.oracle
    for key, quantity in name_quantities.items():
        card = name_cards[key]
        limit = _singleton_limit(card)
        if limit is not None and quantity > limit:
            legality_findings.append(_finding(
                "singleton_violation", "error",
                f"{card.name} has {quantity} copies; its Commander limit is {limit}.",
                card_name=card.name, quantity=quantity, limit=limit,
            ))

    for entry in entries:
        legalities = _json_object(entry.oracle.legalities_json)
        commander_status = legalities.get("commander")
        if commander_status and commander_status != "legal":
            legality_findings.append(_finding(
                "format_illegal_card", "error",
                f"{entry.oracle.name} is {commander_status} in Commander.",
                card_name=entry.oracle.name, status=commander_status,
            ))
        elif not commander_status:
            legality_findings.append(_finding(
                "unknown_legality", "warning",
                f"Commander legality data is missing for {entry.oracle.name}.",
                card_name=entry.oracle.name,
            ))
        off_colors = _color_set(entry.oracle.color_identity) - commander_colors
        if commanders and off_colors:
            legality_findings.append(_finding(
                "color_identity", "error",
                f"{entry.oracle.name} contains colors outside the commander's color identity.",
                card_name=entry.oracle.name,
                card_colors=sorted(_color_set(entry.oracle.color_identity)),
                commander_colors=sorted(commander_colors),
                off_colors=sorted(off_colors),
            ))

    required_by_oracle = {
        entry.oracle.oracle_id: max(0, entry.quantity) for entry in entries
    }
    owned_rows = (
        db.query(CardPrinting.oracle_id, func.coalesce(func.sum(InventoryLine.quantity), 0))
        .join(InventoryLine, InventoryLine.scryfall_id == CardPrinting.scryfall_id)
        .filter(CardPrinting.oracle_id.in_(required_by_oracle or [""]))
        .group_by(CardPrinting.oracle_id)
        .all()
    )
    owned_by_oracle = {oracle_id: int(quantity) for oracle_id, quantity in owned_rows}
    missing = []
    for entry in entries:
        required = required_by_oracle[entry.oracle.oracle_id]
        owned = owned_by_oracle.get(entry.oracle.oracle_id, 0)
        if owned < required:
            missing.append({
                "oracle_id": entry.oracle.oracle_id,
                "name": entry.oracle.name,
                "required": required,
                "owned": owned,
                "shortfall": required - owned,
            })
    missing.sort(key=lambda row: (-row["shortfall"], row["name"]))

    land_count = sum(entry.quantity for entry in entries if _is_land(entry.oracle))
    if land_count < LAND_TARGET[0]:
        health_findings.append(_finding(
            "low_land_count", "warning",
            f"The deck has {land_count} lands; the general target is {LAND_TARGET[0]}–{LAND_TARGET[1]}.",
            actual=land_count, target_min=LAND_TARGET[0], target_max=LAND_TARGET[1],
        ))
    elif land_count > LAND_TARGET[1]:
        health_findings.append(_finding(
            "high_land_count", "warning",
            f"The deck has {land_count} lands; the general target is {LAND_TARGET[0]}–{LAND_TARGET[1]}.",
            actual=land_count, target_min=LAND_TARGET[0], target_max=LAND_TARGET[1],
        ))

    source_counts: Counter[str] = Counter()
    mana_source_total = 0
    for entry in entries:
        produced = _produced_colors(entry, commander_colors)
        if produced:
            mana_source_total += entry.quantity
            for color in produced:
                source_counts[color] += entry.quantity
    demand = _mana_demand(entries)
    if mana_source_total < MANA_SOURCE_MIN:
        health_findings.append(_finding(
            "low_mana_sources", "warning",
            f"The deck has {mana_source_total} direct mana sources; target at least {MANA_SOURCE_MIN}.",
            actual=mana_source_total, target_min=MANA_SOURCE_MIN,
        ))
    for color, symbols in demand.items():
        if source_counts[color] == 0:
            health_findings.append(_finding(
                "missing_color_source", "error",
                f"The deck has {symbols} {color} mana symbols but no detected {color} sources.",
                color=color, mana_symbols=symbols,
            ))

    curve = _curve(entries)
    if curve["average_mana_value"] > AVERAGE_MV_MAX:
        health_findings.append(_finding(
            "high_average_mana_value", "warning",
            f"Average nonland mana value is {curve['average_mana_value']}; target {AVERAGE_MV_MAX:g} or lower.",
            actual=curve["average_mana_value"], target_max=AVERAGE_MV_MAX,
        ))
    if curve["high_mana_value_cards"] > HIGH_MV_MAX:
        health_findings.append(_finding(
            "top_heavy_curve", "warning",
            f"The deck has {curve['high_mana_value_cards']} cards with mana value 6 or greater.",
            actual=curve["high_mana_value_cards"], target_max=HIGH_MV_MAX,
        ))

    role_counts: Counter[str] = Counter()
    role_cards: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        for role in _role_set(entry.oracle):
            role_counts[role] += entry.quantity
            role_cards[role].append(entry.oracle.name)
    role_report: dict[str, Any] = {}
    for role, (minimum, maximum) in ROLE_TARGETS.items():
        count = role_counts[role]
        status = "low" if count < minimum else "high" if count > maximum else "ok"
        role_report[role] = {
            "count": count,
            "target_min": minimum,
            "target_max": maximum,
            "status": status,
            "cards": sorted(set(role_cards[role])),
        }
        if minimum and count < minimum:
            health_findings.append(_finding(
                "role_gap", "warning",
                f"The deck has {count} {role.replace('_', ' ')} cards; target at least {minimum}.",
                role=role, actual=count, target_min=minimum,
            ))

    legality_errors = [f for f in legality_findings if f["severity"] == "error"]
    health_errors = [f for f in health_findings if f["severity"] == "error"]
    health_warnings = [f for f in health_findings if f["severity"] == "warning"]
    health_score = max(0, 100 - len(health_errors) * 15 - len(health_warnings) * 5)

    return {
        "deck_id": deck.id,
        "deterministic": True,
        "legal": not legality_errors,
        "available": not missing,
        "deck_size": {"actual": deck_size, "required": 100, "delta": deck_size - 100},
        "commander": {
            "count": len(commanders),
            "names": [entry.oracle.name for entry in commanders],
            "color_identity": sorted(commander_colors),
        },
        "legality": {"findings": legality_findings},
        "availability": {
            "available": not missing,
            "missing": missing,
            "total_shortfall": sum(row["shortfall"] for row in missing),
        },
        "health": {
            "score": health_score,
            "status": "critical" if health_errors else "needs_attention" if health_warnings else "healthy",
            "lands": {"count": land_count, "target_min": LAND_TARGET[0], "target_max": LAND_TARGET[1]},
            "mana_sources": {
                "total": mana_source_total,
                "target_min": MANA_SOURCE_MIN,
                "by_color": {color: source_counts[color] for color in (*COLORS, "C")},
                "mana_demand": {color: demand[color] for color in COLORS},
            },
            "curve": curve,
            "roles": role_report,
            "findings": health_findings,
        },
    }
