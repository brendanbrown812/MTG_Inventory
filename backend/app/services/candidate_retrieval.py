from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.enrichment.base import profile_from_record
from app.mechanics.evaluation import evaluate_interaction
from app.mechanics.profile import (
    PROFILE_SCHEMA_VERSION,
    TAXONOMY_VERSION,
    HookVerb,
    MechanicProfile,
    UniversalTier,
)
from app.models import (
    CardPrinting,
    InventoryLine,
    MechanicProfileRecord,
    OracleCard,
    RecommendationCardPreference,
)
from app.services.commander_engine import deterministic_roles


RETRIEVAL_VERSION = "1.0.0"
DEFAULT_LIMIT = 200
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CORE_ROLES = {
    "mana_acceleration", "land_ramp", "mana_fixing", "card_advantage",
    "card_selection", "removal", "board_wipe", "protection", "counterspell",
}
_DETERMINISTIC_ROLE_MAP = {
    "ramp": "mana_acceleration",
    "card_draw": "card_advantage",
    "spot_removal": "removal",
    "board_wipes": "board_wipe",
    "protection": "protection",
    "recursion": "recursion",
    "graveyard_hate": "graveyard_hate",
    "counterspells": "counterspell",
    "tutors": "tutor",
}


@dataclass(frozen=True)
class ConceptRule:
    aliases: tuple[str, ...]
    roles: tuple[str, ...] = ()
    mechanics: tuple[str, ...] = ()


_CONCEPT_RULES = (
    ConceptRule(("aristocrats", "death triggers", "dies matters"),
                ("sacrifice_outlet", "sacrifice_payoff", "token_generator"),
                ("sacrifice", "creature_death", "token_creation")),
    ConceptRule(("blink", "flicker", "etb", "enter the battlefield"),
                ("blink", "trigger_multiplier"),
                ("enter_battlefield", "enter_battlefield_triggers")),
    ConceptRule(("landfall", "lands matter"), ("land_payoff", "land_ramp"),
                ("lands_entering", "land_search")),
    ConceptRule(("spellslinger", "spells matter", "instants and sorceries"),
                ("spellslinger_payoff", "cast_payoff"),
                ("instant_or_sorcery_casting", "spell_casting")),
    ConceptRule(("tribal", "typal", "kindred", "creature type"),
                ("typal_payoff",), ("creature_types",)),
    ConceptRule(("graveyard", "reanimator", "recursion"),
                ("recursion", "reanimation", "graveyard_payoff", "self_mill"),
                ("graveyard", "cast_from_graveyard", "lands_in_graveyard")),
    ConceptRule(("tokens", "go wide", "token deck"),
                ("token_generator", "token_multiplier", "token_payoff"),
                ("token_creation", "creature_tokens")),
    ConceptRule(("treasure", "treasures"), ("token_generator", "mana_acceleration"),
                ("treasure_tokens", "artifact_tokens", "sacrifice")),
    ConceptRule(("counters", "plus one counters", "+1/+1 counters"),
                ("counter_payoff", "counter_multiplier"),
                ("counters", "plus_one_counters", "proliferate")),
    ConceptRule(("equipment", "voltron"),
                ("equipment_payoff", "combat_enabler", "protection"),
                ("equipment", "combat_damage", "commander_damage")),
    ConceptRule(("auras", "enchantress", "enchantments"),
                ("aura_payoff", "enchantment_payoff"), ("auras", "enchantments")),
    ConceptRule(("artifacts", "artifact deck"), ("artifact_payoff",),
                ("artifacts", "artifact_activated_abilities")),
    ConceptRule(("lifegain", "life gain"), ("life_gain_payoff",),
                ("life_gain",)),
    ConceptRule(("discard", "madness"), ("discard",), ("card_discard",)),
    ConceptRule(("mill", "self mill"), ("mill", "self_mill"), ("milling", "graveyard")),
    ConceptRule(("deathtouch", "death touch"), ("combat_enabler",), ("deathtouch",)),
    ConceptRule(("poison", "infect", "toxic"), ("poison_payoff",), ("poison_counters",)),
    ConceptRule(("burn", "pinger", "direct damage"), ("direct_damage",),
                ("direct_damage", "damage")),
    ConceptRule(("ramp", "extra mana", "mana acceleration"),
                ("mana_acceleration", "land_ramp"), ("mana", "land_search")),
    ConceptRule(("card draw", "draw cards", "card advantage"),
                ("card_advantage",), ("card_draw",)),
    ConceptRule(("combo", "infinite"), ("combo_enabler",), ())
)


@dataclass(frozen=True)
class KnownCombo:
    cards: tuple[str, ...]
    kind: str
    explanation: str


@lru_cache(maxsize=1)
def _known_combos() -> tuple[KnownCombo, ...]:
    path = Path(__file__).parents[2] / "data" / "known_combos_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        KnownCombo(tuple(item["cards"]), item["kind"], item["explanation"])
        for item in payload["combos"]
    )


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold().replace("+1/+1", "plus one counters"))


def _concepts(text: str) -> tuple[set[str], set[str]]:
    normalized = " ".join(_tokens(text))
    padded = f" {normalized} "
    roles: set[str] = set()
    mechanics: set[str] = set()
    for rule in _CONCEPT_RULES:
        if any(f" {' '.join(_tokens(alias))} " in padded for alias in rule.aliases):
            roles.update(rule.roles)
            mechanics.update(rule.mechanics)
    return roles, mechanics


def _profile_terms(profile: MechanicProfile | None) -> list[str]:
    if profile is None:
        return []
    terms = [role.value for role in profile.roles]
    for hook in profile.hooks:
        terms.extend((hook.verb.value, hook.mechanic.value, hook.condition.value, hook.scope.value))
    terms.extend(reason.value for reason in profile.universal_utility.reasons)
    return terms


def _semantic_terms(text: str, profile: MechanicProfile | None = None) -> list[str]:
    raw = _tokens(text)
    roles, mechanics = _concepts(text)
    expanded = raw + list(roles) + list(mechanics) + _profile_terms(profile)
    return [part for value in expanded for part in value.split("_") if part]


def _tfidf_cosines(query_terms: list[str], documents: list[list[str]]) -> list[float]:
    if not query_terms or not documents:
        return [0.0] * len(documents)
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(set(document))
    count = len(documents)
    idf = {
        term: math.log((1 + count) / (1 + frequency)) + 1
        for term, frequency in document_frequency.items()
    }

    def vector(terms: list[str]) -> dict[str, float]:
        frequencies = Counter(terms)
        return {term: frequency * idf.get(term, math.log(1 + count) + 1)
                for term, frequency in frequencies.items()}

    query = vector(query_terms)
    query_norm = math.sqrt(sum(value * value for value in query.values()))
    scores: list[float] = []
    for document in documents:
        candidate = vector(document)
        candidate_norm = math.sqrt(sum(value * value for value in candidate.values()))
        dot = sum(value * candidate.get(term, 0.0) for term, value in query.items())
        scores.append(dot / (query_norm * candidate_norm) if query_norm and candidate_norm else 0.0)
    return scores


def _color_set(value: str | None) -> set[str]:
    if not value:
        return set()
    stripped = value.strip()
    if stripped.startswith("["):
        try:
            return {str(item) for item in json.loads(stripped)}
        except json.JSONDecodeError:
            pass
    return {char for char in stripped if char in "WUBRG"}


def _known_combo_score(candidate_name: str, seed_names: set[str]) -> tuple[float, list[str]]:
    candidate = candidate_name.casefold()
    seeds = {name.casefold() for name in seed_names}
    best = 0.0
    reasons: list[str] = []
    for combo in _known_combos():
        members = {name.casefold() for name in combo.cards}
        if candidate not in members or not (members - {candidate}) <= seeds:
            continue
        score = 30.0 if combo.kind != "known_synergy" else 18.0
        if score > best:
            best = score
            partners = ", ".join(
                name for name in combo.cards if name.casefold() != candidate
            )
            reasons = [f"Known {combo.kind.replace('_', ' ')} with {partners}: {combo.explanation}"]
    return best, reasons


def retrieve_owned_candidates(
    db: Session,
    query_text: str,
    *,
    seed_names: set[str] | None = None,
    commander_name: str | None = None,
    exclude_names: set[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Rank owned Commander-legal cards with transparent deterministic components."""
    seed_names = {name.casefold() for name in (seed_names or set())}
    exclude_names = {name.casefold() for name in (exclude_names or set())}

    rows = (
        db.query(CardPrinting, OracleCard, MechanicProfileRecord, func.sum(InventoryLine.quantity))
        .select_from(CardPrinting)
        .join(OracleCard, OracleCard.oracle_id == CardPrinting.oracle_id)
        .join(InventoryLine, InventoryLine.scryfall_id == CardPrinting.scryfall_id)
        .outerjoin(
            MechanicProfileRecord,
            (MechanicProfileRecord.oracle_id == OracleCard.oracle_id)
            & MechanicProfileRecord.is_current.is_(True)
            & (MechanicProfileRecord.schema_version == PROFILE_SCHEMA_VERSION)
            & (MechanicProfileRecord.taxonomy_version == TAXONOMY_VERSION),
        )
        .filter(func.json_extract(OracleCard.legalities_json, "$.commander") == "legal")
        .group_by(OracleCard.oracle_id, MechanicProfileRecord.id)
        .all()
    )

    commander_identity: set[str] | None = None
    commander_found = commander_name is None
    if commander_name:
        for _, oracle, _, _ in rows:
            if oracle.name.casefold() == commander_name.casefold():
                commander_identity = _color_set(oracle.color_identity)
                seed_names.add(oracle.name.casefold())
                commander_found = True
                break
    if not commander_found:
        return []

    # Names explicitly written in a theme become seeds when the card is owned.
    normalized_query = " ".join(_tokens(query_text))
    for _, oracle, _, _ in rows:
        if " ".join(_tokens(oracle.name)) in normalized_query:
            seed_names.add(oracle.name.casefold())

    seed_profiles: list[MechanicProfile] = []
    seed_deterministic_roles: set[str] = set()
    seed_texts: list[str] = []
    for _, oracle, record, _ in rows:
        if oracle.name.casefold() not in seed_names:
            continue
        seed_texts.append(" ".join(filter(None, (
            oracle.type_line, oracle.oracle_text, oracle.keywords,
        ))))
        seed_deterministic_roles.update(
            _DETERMINISTIC_ROLE_MAP[role]
            for role in deterministic_roles(oracle)
            if role in _DETERMINISTIC_ROLE_MAP
        )
        if record is not None:
            seed_profiles.append(profile_from_record(record))

    target_roles, target_mechanics = _concepts(query_text)
    query_parts = [query_text, *seed_texts, *seed_deterministic_roles]
    for profile in seed_profiles:
        query_parts.extend(_profile_terms(profile))

    candidates: list[
        tuple[CardPrinting, OracleCard, MechanicProfile | None, int, set[str], set[str]]
    ] = []
    documents: list[list[str]] = []
    for printing, oracle, record, quantity in rows:
        if oracle.name.casefold() in exclude_names:
            continue
        if commander_identity is not None and not _color_set(oracle.color_identity) <= commander_identity:
            continue
        profile = profile_from_record(record) if record is not None else None
        raw_deterministic_roles = deterministic_roles(oracle)
        mapped_deterministic_roles = {
            _DETERMINISTIC_ROLE_MAP[role]
            for role in raw_deterministic_roles
            if role in _DETERMINISTIC_ROLE_MAP
        }
        candidates.append((
            printing, oracle, profile, int(quantity or 0),
            raw_deterministic_roles, mapped_deterministic_roles,
        ))
        document_text = " ".join(filter(None, (
            oracle.type_line, oracle.oracle_text, oracle.keywords,
        )))
        documents.append(
            _semantic_terms(document_text, profile)
            + [part for role in mapped_deterministic_roles for part in role.split("_")]
        )

    semantic_scores = _tfidf_cosines(
        _semantic_terms(" ".join(query_parts)), documents
    )
    preference_by_oracle = {
        preference.oracle_id: preference
        for preference in db.query(RecommendationCardPreference).filter(
            RecommendationCardPreference.oracle_id.in_(
                [oracle.oracle_id for _, oracle, _, _, _, _ in candidates] or [""]
            )
        ).all()
    }

    seed_roles = seed_deterministic_roles | {
        role.value for profile in seed_profiles for role in profile.roles
    }
    missing_core_roles = _CORE_ROLES - seed_roles
    ranked: list[dict] = []
    for (
        printing, oracle, profile, quantity, raw_deterministic_roles,
        mapped_deterministic_roles,
    ), cosine in zip(candidates, semantic_scores):
        roles = ({role.value for role in profile.roles} if profile else set()) | mapped_deterministic_roles
        hooks = profile.hooks if profile else []
        mechanics = {hook.mechanic.value for hook in hooks}
        reasons: list[str] = []

        matched_roles = target_roles & roles
        role_score = 24.0 * len(matched_roles) / max(1, len(target_roles)) if target_roles else 0.0
        core_roles = roles & _CORE_ROLES
        fills_missing = core_roles & missing_core_roles
        already_covered = core_roles - fills_missing
        functional_score = min(8.0, 2.0 * len(fills_missing) + 0.5 * len(already_covered))
        if matched_roles:
            reasons.append("Role match: " + ", ".join(sorted(matched_roles)))
        if fills_missing:
            reasons.append("Fills missing deck function: " + ", ".join(sorted(fills_missing)))
        if already_covered:
            reasons.append("Additional deck function: " + ", ".join(sorted(already_covered)))

        matched_mechanics = target_mechanics & mechanics
        relationship_score = (
            12.0 * len(matched_mechanics) / max(1, len(target_mechanics))
            if target_mechanics else 0.0
        )
        if matched_mechanics:
            reasons.append("Mechanic match: " + ", ".join(sorted(matched_mechanics)))

        anti_penalty = 0.0
        for seed in seed_profiles:
            interaction = evaluate_interaction(seed, profile) if profile else None
            if interaction is None or interaction.outcome == "neutral":
                continue
            if interaction.outcome == "anti_synergy":
                anti_penalty = max(anti_penalty, 24.0)
            elif interaction.outcome == "conditional_combo":
                relationship_score = max(relationship_score, 24.0)
            elif interaction.outcome == "synergy":
                relationship_score = max(relationship_score, 16.0)
            elif interaction.outcome == "universal_fit":
                relationship_score = max(relationship_score, 4.0)
            reasons.extend(interaction.reasons)

        combo_score, combo_reasons = _known_combo_score(oracle.name, seed_names)
        reasons.extend(combo_reasons)
        semantic_score = 25.0 * cosine
        if semantic_score >= 2:
            reasons.append(f"Semantic MTG concept similarity: {cosine:.3f}")

        universal_score = 0.0
        if profile and profile.universal_utility.tier is UniversalTier.broad:
            universal_score = 6.0
            reasons.append("Broad universal utility")
        elif profile and profile.universal_utility.tier is UniversalTier.contextual:
            universal_score = 2.0

        # Basic lands stay available to the deck constructor without masquerading
        # as thematic hits.
        land_floor = 1.0 if oracle.type_line and "Basic Land" in oracle.type_line else 0.0
        preference = preference_by_oracle.get(oracle.oracle_id)
        user_feedback_score = 0.0
        if preference is not None:
            total_feedback = preference.accepted_count + preference.rejected_count
            user_feedback_score = 12.0 * (
                preference.accepted_count - preference.rejected_count
            ) / (total_feedback + 2)
            if user_feedback_score:
                reasons.append(
                    "Your prior feedback: "
                    f"{preference.accepted_count} accepted, "
                    f"{preference.rejected_count} rejected"
                )
        components = {
            "role": role_score,
            "mechanic_relationship": relationship_score,
            "semantic": semantic_score,
            "known_combo": combo_score,
            "universal_utility": universal_score,
            "functional_role": functional_score,
            "basic_land_floor": land_floor,
            "user_feedback": user_feedback_score,
            "anti_synergy_penalty": -anti_penalty if anti_penalty else 0.0,
        }
        total = sum(components.values())
        try:
            keywords = json.loads(oracle.keywords or "[]")
        except (json.JSONDecodeError, TypeError):
            keywords = []
        ranked.append({
            "scryfall_id": printing.scryfall_id,
            "oracle_id": oracle.oracle_id,
            "name": oracle.name,
            "mana_cost": oracle.mana_cost,
            "cmc": oracle.cmc,
            "type_line": oracle.type_line,
            "oracle_text": oracle.oracle_text,
            "color_identity": oracle.color_identity,
            "keywords": keywords,
            "owned_quantity": quantity,
            "deterministic_roles": sorted(raw_deterministic_roles),
            "mechanic_profile": profile.model_dump(mode="json") if profile else None,
            "retrieval": {
                "version": RETRIEVAL_VERSION,
                "total_score": round(total, 4),
                "components": {key: round(value, 4) for key, value in components.items()},
                "reasons": list(dict.fromkeys(reasons)),
            },
        })

    ranked.sort(key=lambda item: (-item["retrieval"]["total_score"], item["name"].casefold()))
    selected = ranked[:limit]
    selected_ids = {item["oracle_id"] for item in selected}
    pinned = [item for item in ranked if item["name"].casefold() in seed_names]
    protected_ids = {item["oracle_id"] for item in pinned}
    replacement_index = len(selected) - 1
    for item in pinned:
        if item["oracle_id"] in selected_ids:
            continue
        if len(selected) < limit:
            selected.append(item)
        else:
            while (
                replacement_index >= 0
                and selected[replacement_index]["oracle_id"] in protected_ids
            ):
                replacement_index -= 1
            if replacement_index < 0:
                break
            selected_ids.discard(selected[replacement_index]["oracle_id"])
            selected[replacement_index] = item
            replacement_index -= 1
        selected_ids.add(item["oracle_id"])
    missing_basics = [
        item for item in ranked
        if item["oracle_id"] not in selected_ids
        and item["type_line"] and "Basic Land" in item["type_line"]
    ]
    replacement_index = len(selected) - 1
    for basic in missing_basics:
        if len(selected) < limit:
            selected.append(basic)
        else:
            while (
                replacement_index >= 0
                and (
                    selected[replacement_index]["oracle_id"] in protected_ids
                    or (
                        selected[replacement_index]["type_line"]
                        and "Basic Land" in selected[replacement_index]["type_line"]
                    )
                )
            ):
                replacement_index -= 1
            if replacement_index < 0:
                break
            selected_ids.discard(selected[replacement_index]["oracle_id"])
            selected[replacement_index] = basic
            replacement_index -= 1
        selected_ids.add(basic["oracle_id"])
    selected.sort(key=lambda item: (-item["retrieval"]["total_score"], item["name"].casefold()))
    return selected


def public_score_summary(candidates: list[dict], limit: int = 25) -> dict:
    return {
        "version": RETRIEVAL_VERSION,
        "component_ranges": {
            "role": [0, 24],
            "mechanic_relationship": [0, 24],
            "semantic": [0, 25],
            "known_combo": [0, 30],
            "universal_utility": [0, 6],
            "functional_role": [0, 8],
            "basic_land_floor": [0, 1],
            "user_feedback": [-12, 12],
            "anti_synergy_penalty": [-24, 0],
        },
        "candidates": [
            {
                "name": card["name"],
                "owned_quantity": card["owned_quantity"],
                **card["retrieval"],
            }
            for card in candidates[:limit]
        ],
    }
