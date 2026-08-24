from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.mechanics.profile import Role
from app.models import CardPrinting
from app.reasoning.base import ReasoningProposal
from app.services.commander_engine import (
    ROLE_TARGETS,
    commander_eligibility,
    singleton_limit,
)


OPTIMIZER_VERSION = "1.0.0"
DECK_SIZE = 100
LAND_TARGET = 37
NONLAND_TARGET = DECK_SIZE - LAND_TARGET
MAX_UTILITY_LANDS = 12
_BASIC_BY_COLOR = {"W": "plains", "U": "island", "B": "swamp", "R": "mountain", "G": "forest"}


def _color_set(value: str | None) -> set[str]:
    if not value:
        return set()
    stripped = value.strip()
    if stripped.startswith("["):
        try:
            return {str(item).upper() for item in json.loads(stripped)}
        except json.JSONDecodeError:
            pass
    return {char for char in stripped.upper() if char in "WUBRG"}


def _is_land(card: dict) -> bool:
    return "land" in (card.get("type_line") or "").casefold()


def _is_basic(card: dict) -> bool:
    type_line = (card.get("type_line") or "").casefold()
    return "basic" in type_line and "land" in type_line


def _candidate_value(card: dict, proposal: ReasoningProposal) -> float:
    value = float((card.get("retrieval") or {}).get("total_score", 0))
    priority = proposal.card_priorities.get(card["name"], 0)
    value += priority * 15
    for package in proposal.packages:
        if card["name"] in package.card_names:
            value += package.priority * 20
    # Prefer a smoother curve when strategic value is otherwise similar.
    mana_value = float(card.get("cmc") or 0)
    if not _is_land(card):
        value += max(0.0, 3.5 - abs(mana_value - 3.0))
    return value


def format_decklist(entries: list[dict]) -> str:
    commander = [entry for entry in entries if entry["is_commander"]]
    rest = sorted(
        (entry for entry in entries if not entry["is_commander"]),
        key=lambda entry: entry["name"].casefold(),
    )
    return "\n".join(
        f"{entry['quantity']} {entry['name']}" for entry in [*commander, *rest]
    )


def validate_optimized_deck(
    db: Session,
    candidates: list[dict],
    entries: list[dict],
) -> dict[str, Any]:
    """Validate only hard, machine-enforceable Commander and collection constraints."""
    pool = {card["oracle_id"]: card for card in candidates}
    errors: list[dict[str, Any]] = []
    total = sum(entry["quantity"] for entry in entries)
    commanders = [entry for entry in entries if entry["is_commander"]]

    if total != DECK_SIZE:
        errors.append({"code": "deck_size", "actual": total, "required": DECK_SIZE})
    if len(commanders) != 1 or (commanders and commanders[0]["quantity"] != 1):
        errors.append({"code": "commander_count", "actual": len(commanders), "required": 1})

    commander_colors: set[str] = set()
    if len(commanders) == 1:
        commander_card = pool.get(commanders[0]["oracle_id"])
        if commander_card is None:
            errors.append({"code": "commander_outside_pool", "name": commanders[0]["name"]})
        else:
            commander_colors = _color_set(commander_card.get("color_identity"))
            printing = db.get(CardPrinting, commander_card["scryfall_id"])
            eligible, reason = commander_eligibility(printing) if printing else (False, "printing missing")
            if not eligible:
                errors.append({
                    "code": "ineligible_commander", "name": commander_card["name"],
                    "reason": reason,
                })

    seen_names: set[str] = set()
    for entry in entries:
        card = pool.get(entry["oracle_id"])
        if card is None:
            errors.append({"code": "outside_candidate_pool", "name": entry["name"]})
            continue
        if entry.get("scryfall_id") != card["scryfall_id"]:
            errors.append({
                "code": "printing_outside_candidate_pool", "name": entry["name"]
            })
        if entry.get("name") != card["name"]:
            errors.append({
                "code": "card_name_mismatch", "name": entry.get("name"),
                "expected": card["name"],
            })
        name_key = card["name"].casefold()
        if name_key in seen_names:
            errors.append({"code": "duplicate_entry", "name": card["name"]})
        seen_names.add(name_key)
        quantity = entry["quantity"]
        if quantity < 1:
            errors.append({"code": "invalid_quantity", "name": card["name"], "quantity": quantity})
        if quantity > int(card.get("owned_quantity") or 0):
            errors.append({
                "code": "availability", "name": card["name"], "required": quantity,
                "owned": int(card.get("owned_quantity") or 0),
            })
        printing = db.get(CardPrinting, card["scryfall_id"])
        if printing is None:
            errors.append({"code": "printing_missing", "name": card["name"]})
            continue
        limit = singleton_limit(printing.oracle)
        if limit is not None and quantity > limit:
            errors.append({
                "code": "singleton", "name": card["name"],
                "quantity": quantity, "limit": limit,
            })
        try:
            commander_status = json.loads(printing.oracle.legalities_json or "{}").get("commander")
        except (json.JSONDecodeError, TypeError):
            commander_status = None
        if commander_status != "legal":
            errors.append({
                "code": "commander_legality", "name": card["name"],
                "status": commander_status,
            })
        off_colors = _color_set(card.get("color_identity")) - commander_colors
        if commanders and off_colors:
            errors.append({
                "code": "color_identity", "name": card["name"],
                "off_colors": sorted(off_colors),
            })

    checks = {
        "bounded_candidate_pool": not any(
            e["code"] in {
                "outside_candidate_pool", "printing_outside_candidate_pool", "card_name_mismatch",
            }
            for e in errors
        ),
        "exactly_100_cards": total == DECK_SIZE,
        "one_eligible_commander": not any(
            e["code"] in {"commander_count", "commander_outside_pool", "ineligible_commander"}
            for e in errors
        ),
        "commander_legal": not any(e["code"] == "commander_legality" for e in errors),
        "color_identity": not any(e["code"] == "color_identity" for e in errors),
        "singleton": not any(e["code"] in {"singleton", "duplicate_entry"} for e in errors),
        "owned_quantities": not any(e["code"] == "availability" for e in errors),
    }
    return {"valid": not errors, "checks": checks, "errors": errors}


@dataclass
class _Assembly:
    commander_name: str
    entries: list[dict]
    package_report: list[dict]
    objective_score: float
    validation: dict[str, Any]


def _assemble_for_commander(
    db: Session,
    candidates: list[dict],
    proposal: ReasoningProposal,
    commander: dict,
) -> _Assembly:
    commander_colors = _color_set(commander.get("color_identity"))
    eligible = [
        card for card in candidates
        if _color_set(card.get("color_identity")) <= commander_colors
    ]
    by_name = {card["name"].casefold(): card for card in eligible}
    values = {card["oracle_id"]: _candidate_value(card, proposal) for card in eligible}
    ranked = sorted(
        eligible,
        key=lambda card: (-values[card["oracle_id"]], card["name"].casefold()),
    )
    selected: dict[str, int] = {}

    def total() -> int:
        return sum(selected.values())

    def capacity(card: dict) -> int:
        printing = db.get(CardPrinting, card["scryfall_id"])
        if printing is None:
            return 0
        copy_limit = singleton_limit(printing.oracle)
        owned = int(card.get("owned_quantity") or 0)
        return owned if copy_limit is None else min(owned, copy_limit)

    def add(card: dict, requested: int = 1) -> int:
        if total() >= DECK_SIZE:
            return 0
        current = selected.get(card["oracle_id"], 0)
        amount = min(requested, capacity(card) - current, DECK_SIZE - total())
        if amount > 0:
            selected[card["oracle_id"]] = current + amount
        return max(0, amount)

    add(commander)

    for package in sorted(proposal.packages, key=lambda item: (-item.priority, item.name.casefold())):
        package_cards = [
            by_name[name.casefold()] for name in package.card_names
            if name.casefold() in by_name
        ]
        package_cards.sort(
            key=lambda card: (-values[card["oracle_id"]], card["name"].casefold())
        )
        already = sum(1 for card in package_cards if selected.get(card["oracle_id"], 0))
        for card in package_cards:
            if already >= package.minimum_cards:
                break
            if selected.get(card["oracle_id"], 0) == 0 and add(card):
                already += 1

    # Deterministic deck-health role floors are filled before generic value picks.
    for role, (minimum, _) in ROLE_TARGETS.items():
        if minimum <= 0:
            continue
        def role_count() -> int:
            return sum(
                quantity for oracle_id, quantity in selected.items()
                if role in next(
                    (set(card.get("deterministic_roles", [])) for card in eligible
                     if card["oracle_id"] == oracle_id),
                    set(),
                )
            )
        role_cards = [
            card for card in ranked
            if not _is_land(card) and role in set(card.get("deterministic_roles", []))
        ]
        for card in role_cards:
            if role_count() >= minimum:
                break
            add(card)

    for card in ranked:
        nonland_count = sum(
            quantity for oracle_id, quantity in selected.items()
            if not _is_land(next(item for item in eligible if item["oracle_id"] == oracle_id))
        )
        if nonland_count >= NONLAND_TARGET:
            break
        if not _is_land(card):
            add(card)

    nonbasic_lands = [card for card in ranked if _is_land(card) and not _is_basic(card)]
    for card in nonbasic_lands[:MAX_UTILITY_LANDS]:
        if sum(
            quantity for oracle_id, quantity in selected.items()
            if _is_land(next(item for item in eligible if item["oracle_id"] == oracle_id))
        ) >= LAND_TARGET:
            break
        add(card)

    basics = [card for card in eligible if _is_basic(card)]
    preferred_basic_names = [_BASIC_BY_COLOR[color] for color in "WUBRG" if color in commander_colors]
    if not preferred_basic_names:
        preferred_basic_names = ["wastes"]
    basics.sort(key=lambda card: (
        preferred_basic_names.index(card["name"].casefold())
        if card["name"].casefold() in preferred_basic_names else len(preferred_basic_names),
        card["name"].casefold(),
    ))
    while total() < DECK_SIZE:
        land_count = sum(
            quantity for oracle_id, quantity in selected.items()
            if _is_land(next(item for item in eligible if item["oracle_id"] == oracle_id))
        )
        if land_count >= LAND_TARGET:
            break
        progress = sum(add(card) for card in basics)
        if progress == 0:
            break

    # Fill any remaining slots from bounded candidates, respecting each copy limit.
    while total() < DECK_SIZE:
        progress = 0
        for card in ranked:
            progress += add(card)
            if total() >= DECK_SIZE:
                break
        if progress == 0:
            break

    entry_cards = {card["oracle_id"]: card for card in eligible}
    entries = [
        {
            "oracle_id": oracle_id,
            "scryfall_id": entry_cards[oracle_id]["scryfall_id"],
            "name": entry_cards[oracle_id]["name"],
            "quantity": quantity,
            "is_commander": oracle_id == commander["oracle_id"],
            "selection_score": round(values[oracle_id], 4),
        }
        for oracle_id, quantity in selected.items()
    ]
    entries.sort(key=lambda entry: (not entry["is_commander"], entry["name"].casefold()))
    validation = validate_optimized_deck(db, candidates, entries)
    package_report = []
    selected_names = {entry["name"] for entry in entries}
    for package in proposal.packages:
        included = [name for name in package.card_names if name in selected_names]
        package_report.append({
            "name": package.name,
            "purpose": package.purpose,
            "priority": package.priority,
            "minimum_cards": package.minimum_cards,
            "maximum_cards": package.maximum_cards,
            "included_cards": included,
            "included_count": len(included),
            "minimum_satisfied": len(included) >= package.minimum_cards,
        })
    objective = sum(values[entry["oracle_id"]] * entry["quantity"] for entry in entries)
    return _Assembly(commander["name"], entries, package_report, round(objective, 4), validation)


def optimize_commander_deck(
    db: Session,
    candidates: list[dict],
    proposal: ReasoningProposal,
    preferred_commander: str | None = None,
) -> dict[str, Any]:
    """Assemble the final deck; model output is advisory and cannot bypass constraints."""
    by_name = {card["name"].casefold(): card for card in candidates}
    requested = preferred_commander
    commander_candidates: list[dict] = []
    if requested:
        card = by_name.get(requested.casefold())
        if card is None:
            return {
                "version": OPTIMIZER_VERSION, "feasible": False, "commander": requested,
                "entries": [], "decklist": "", "package_report": [],
                "objective_score": 0,
                "validation": {"valid": False, "checks": {}, "errors": [
                    {"code": "commander_outside_candidate_pool", "name": requested}
                ]},
            }
        commander_candidates.append(card)
    else:
        commander_candidates = sorted(
            candidates,
            key=lambda card: (
                -_candidate_value(card, proposal), card["name"].casefold()
            ),
        )
        if proposal.recommended_commander:
            recommended = by_name.get(proposal.recommended_commander.casefold())
            if recommended is not None:
                commander_candidates = [
                    recommended,
                    *(card for card in commander_candidates if card is not recommended),
                ]

    eligible_commanders: list[dict] = []
    for card in commander_candidates:
        printing = db.get(CardPrinting, card["scryfall_id"])
        if printing and commander_eligibility(printing)[0]:
            eligible_commanders.append(card)
        if preferred_commander:
            break

    if not eligible_commanders:
        attempted_commander = preferred_commander or proposal.recommended_commander
        return {
            "version": OPTIMIZER_VERSION, "feasible": False, "commander": attempted_commander,
            "entries": [], "decklist": "", "package_report": [],
            "objective_score": 0,
            "validation": {"valid": False, "checks": {}, "errors": [
                {"code": "no_eligible_commander", "name": attempted_commander}
            ]},
        }

    best: _Assembly | None = None
    for commander in eligible_commanders:
        assembly = _assemble_for_commander(db, candidates, proposal, commander)
        if best is None or (
            assembly.validation["valid"], sum(e["quantity"] for e in assembly.entries), assembly.objective_score
        ) > (
            best.validation["valid"], sum(e["quantity"] for e in best.entries), best.objective_score
        ):
            best = assembly
        if assembly.validation["valid"]:
            break

    assert best is not None
    return {
        "version": OPTIMIZER_VERSION,
        "feasible": best.validation["valid"],
        "commander": best.commander_name,
        "entries": best.entries,
        "decklist": format_decklist(best.entries),
        "package_report": best.package_report,
        "objective_score": best.objective_score,
        "validation": best.validation,
    }
