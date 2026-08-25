from __future__ import annotations

from dataclasses import dataclass

from app.reasoning.base import ReasoningProposal, StrategyPackage


DETERMINISTIC_REASONER_VERSION = "rules-v1"


@dataclass(frozen=True)
class _PackageSpec:
    name: str
    purpose: str
    deterministic_roles: frozenset[str]
    structured_roles: frozenset[str]
    priority: float
    minimum: int
    maximum: int


_PACKAGE_SPECS = (
    _PackageSpec(
        "Mana development",
        "Accelerate and fix mana so the deck can execute its plan on time.",
        frozenset({"ramp"}),
        frozenset({"mana_acceleration", "mana_fixing", "land_ramp", "cost_reduction", "ritual"}),
        0.72,
        8,
        12,
    ),
    _PackageSpec(
        "Card flow",
        "Maintain access to cards through draw, selection, and repeatable advantage.",
        frozenset({"card_draw"}),
        frozenset({"card_advantage", "card_selection", "looting", "wheel"}),
        0.70,
        8,
        12,
    ),
    _PackageSpec(
        "Interaction",
        "Answer opposing threats with a mixture of targeted and broad interaction.",
        frozenset({"spot_removal", "board_wipes", "counterspells", "graveyard_hate"}),
        frozenset({"removal", "board_wipe", "counterspell", "graveyard_hate", "hate_piece"}),
        0.66,
        8,
        14,
    ),
    _PackageSpec(
        "Resilience",
        "Protect important pieces and recover resources after disruption.",
        frozenset({"protection", "recursion"}),
        frozenset({"protection", "recursion", "reanimation", "graveyard_recycling"}),
        0.56,
        4,
        10,
    ),
)


def _retrieval(card: dict) -> dict:
    value = card.get("retrieval")
    return value if isinstance(value, dict) else {}


def _components(card: dict) -> dict[str, float]:
    value = _retrieval(card).get("components")
    if not isinstance(value, dict):
        return {}
    return {
        str(key): float(score)
        for key, score in value.items()
        if isinstance(score, (int, float))
    }


def _score(card: dict) -> float:
    value = _retrieval(card).get("total_score", 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _is_land(card: dict) -> bool:
    return "land" in str(card.get("type_line") or "").casefold()


def _likely_commander(card: dict) -> bool:
    type_line = str(card.get("type_line") or "").casefold()
    oracle_text = str(card.get("oracle_text") or "").casefold()
    return (
        ("legendary" in type_line and "creature" in type_line)
        or "can be your commander" in oracle_text
    )


def _structured_roles(card: dict) -> set[str]:
    profile = card.get("mechanic_profile")
    if not isinstance(profile, dict):
        return set()
    roles = profile.get("roles")
    return {str(role) for role in roles} if isinstance(roles, list) else set()


def _deterministic_roles(card: dict) -> set[str]:
    roles = card.get("deterministic_roles")
    return {str(role) for role in roles} if isinstance(roles, list) else set()


def _ranked(cards: list[dict]) -> list[dict]:
    return sorted(cards, key=lambda card: (-_score(card), str(card["name"]).casefold()))


class DeterministicStrategyReasoner:
    """Create advisory packages from a closed candidate pool without a model call."""

    provider_name = "deterministic"

    def __init__(self, model: str = DETERMINISTIC_REASONER_VERSION):
        self._model = model or DETERMINISTIC_REASONER_VERSION

    @property
    def model_name(self) -> str:
        return self._model

    def propose(
        self,
        theme: str,
        candidates: list[dict],
        commander_name: str | None,
    ) -> ReasoningProposal:
        if not candidates:
            return ReasoningProposal(
                strategy_summary="No owned candidates were available for deterministic planning."
            )

        normalized_theme = " ".join(theme.split()) or "a balanced Commander deck"
        package_theme = normalized_theme[:240]
        summary_theme = normalized_theme[:600]

        canonical = {str(card["name"]).casefold(): str(card["name"]) for card in candidates}
        recommended_commander = canonical.get(commander_name.casefold()) if commander_name else None
        if recommended_commander is None:
            commander_candidates = _ranked([card for card in candidates if _likely_commander(card)])
            if commander_candidates:
                recommended_commander = str(commander_candidates[0]["name"])

        packages: list[StrategyPackage] = []
        commander_key = recommended_commander.casefold() if recommended_commander else None
        nonland = [
            card for card in candidates
            if not _is_land(card) and str(card["name"]).casefold() != commander_key
        ]

        thematic = []
        for card in nonland:
            components = _components(card)
            theme_signal = sum(
                components.get(component, 0.0)
                for component in ("role", "mechanic_relationship", "semantic", "known_combo")
            ) + components.get("anti_synergy_penalty", 0.0)
            if theme_signal > 0:
                thematic.append((theme_signal, card))
        thematic.sort(key=lambda item: (-item[0], str(item[1]["name"]).casefold()))
        theme_cards = [str(card["name"]) for _, card in thematic[:16]]
        if theme_cards:
            packages.append(StrategyPackage(
                name="Theme engine",
                purpose=f"Advance the requested {package_theme} strategy using the strongest local mechanic matches.",
                card_names=theme_cards,
                priority=0.86,
                minimum_cards=min(8, len(theme_cards)),
                maximum_cards=min(16, len(theme_cards)),
            ))

        combo_cards = [
            str(card["name"])
            for card in _ranked(nonland)
            if _components(card).get("known_combo", 0) > 0
        ][:12]
        if combo_cards:
            packages.append(StrategyPackage(
                name="Known interactions",
                purpose="Preserve locally catalogued combo or high-confidence interaction pieces.",
                card_names=combo_cards,
                priority=0.92,
                minimum_cards=min(2, len(combo_cards)),
                maximum_cards=len(combo_cards),
            ))

        for spec in _PACKAGE_SPECS:
            matching = [
                card for card in nonland
                if (
                    _deterministic_roles(card) & spec.deterministic_roles
                    or _structured_roles(card) & spec.structured_roles
                )
            ]
            names = [str(card["name"]) for card in _ranked(matching)[:spec.maximum]]
            if not names:
                continue
            packages.append(StrategyPackage(
                name=spec.name,
                purpose=spec.purpose,
                card_names=names,
                priority=spec.priority,
                minimum_cards=min(spec.minimum, len(names)),
                maximum_cards=len(names),
            ))

        priority_candidates = _ranked(nonland)
        positive_scores = [max(0.0, _score(card)) for card in priority_candidates]
        maximum_score = max(positive_scores, default=0.0)
        card_priorities = {
            str(card["name"]): round(max(0.0, _score(card)) / maximum_score, 4)
            for card in priority_candidates[:100]
            if maximum_score > 0 and _score(card) > 0
        }
        if recommended_commander:
            card_priorities[recommended_commander] = 1.0

        package_names = ", ".join(package.name.casefold() for package in packages)
        commander_clause = (
            f" around {recommended_commander}" if recommended_commander else " with the best eligible owned commander"
        )
        strategy_summary = (
            f"Build {summary_theme}{commander_clause}. "
            f"The local planner ranked only owned candidates and organized them into "
            f"{package_names or 'retrieval-priority groups'}; deterministic code will choose quantities and enforce every hard constraint."
        )
        return ReasoningProposal(
            strategy_summary=strategy_summary,
            recommended_commander=recommended_commander,
            packages=packages[:12],
            card_priorities=card_priorities,
        )
