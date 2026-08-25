from __future__ import annotations

from collections import Counter

from app.review.base import (
    AuditReview,
    CardRecommendation,
    ReplacementRecommendation,
    SuggestReview,
)


DETERMINISTIC_REVIEW_VERSION = "rules-v1"
_CORE_ROLE_LABELS = {
    "ramp": "mana acceleration",
    "card_draw": "card advantage",
    "spot_removal": "targeted interaction",
    "board_wipes": "board wipes",
    "protection": "protection",
    "recursion": "recursion",
}


def _score(card: dict) -> float:
    value = (card.get("retrieval") or {}).get("total_score", 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _ranked(candidates: list[dict]) -> list[dict]:
    return sorted(candidates, key=lambda card: (-_score(card), str(card["name"]).casefold()))


def _candidate_reason(card: dict) -> str:
    retrieval = card.get("retrieval") or {}
    reasons = retrieval.get("reasons") or []
    if reasons:
        return str(reasons[0])
    roles = card.get("deterministic_roles") or []
    if roles:
        return "Adds " + ", ".join(str(role).replace("_", " ") for role in roles[:3]) + "."
    return "Ranks highly among the owned, legal candidates for this deck context."


def _role_counts(existing_cards: list[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for card in existing_cards:
        quantity = max(1, int(card.get("quantity", 1)))
        counts.update({str(role): quantity for role in card.get("deterministic_roles", [])})
    return counts


def _cut_candidates(existing_cards: list[dict], limit: int) -> list[dict]:
    eligible = [
        card for card in existing_cards
        if "land" not in str(card.get("type_line") or "").casefold()
        and "legendary creature" not in str(card.get("type_line") or "").casefold()
    ]
    return sorted(
        eligible,
        key=lambda card: (
            bool(card.get("deterministic_roles")),
            -float(card.get("cmc") or 0),
            str(card.get("name") or "").casefold(),
        ),
    )[:limit]


class DeterministicDeckReviewer:
    provider_name = "deterministic"

    def __init__(self, model: str = DETERMINISTIC_REVIEW_VERSION):
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def suggest(self, current_list, candidates, theme_hint, existing_cards) -> SuggestReview:
        ranked = _ranked(candidates)[:10]
        cuts = _cut_candidates(existing_cards, min(5, len(ranked)))
        counts = _role_counts(existing_cards)
        missing = [label for role, label in _CORE_ROLE_LABELS.items() if counts[role] == 0]
        theme = " ".join((theme_hint or "").split()) or "the deck's current strategy"
        return SuggestReview(
            theme_assessment=(
                f"Local analysis used the current list as context for {theme}. "
                f"The bounded pool contains {len(candidates)} owned, Commander-legal additions."
            ),
            suggestions=[
                CardRecommendation(name=card["name"], reason=_candidate_reason(card))
                for card in ranked
            ],
            cards_to_consider_cutting=[
                CardRecommendation(
                    name=card["name"],
                    reason="No core functional role was recognized or this occupies an expensive curve slot.",
                )
                for card in cuts
            ],
            viability_note=(
                "Deterministic review found no obvious missing core functions."
                if not missing else "Core functions not recognized in the pasted list: " + ", ".join(missing) + "."
            ),
        )

    def audit(self, decklist, candidates, existing_cards) -> AuditReview:
        ranked = _ranked(candidates)[:10]
        cuts = _cut_candidates(existing_cards, min(10, len(ranked)))
        role_counts = _role_counts(existing_cards)
        lands = sum(
            int(card.get("quantity", 1)) for card in existing_cards
            if "land" in str(card.get("type_line") or "").casefold()
        )
        total = sum(int(card.get("quantity", 1)) for card in existing_cards)
        strengths = [
            f"Recognized {total} cards from the pasted list in the local Oracle database.",
        ]
        if 35 <= lands <= 40:
            strengths.append(f"Land count ({lands}) is within the configured Commander target.")
        weaknesses = [
            f"Land count is {lands}; the configured target is 35–40."
        ] if lands and not 35 <= lands <= 40 else []
        for role, label in _CORE_ROLE_LABELS.items():
            if role_counts[role] == 0:
                weaknesses.append(f"No {label} was recognized by the deterministic role engine.")
        additions = [
            ReplacementRecommendation(
                name=card["name"],
                replaces=cuts[index]["name"] if index < len(cuts) else None,
                reason=_candidate_reason(card),
            )
            for index, card in enumerate(ranked)
        ]
        return AuditReview(
            overall_assessment=(
                "Local deterministic audit complete; strategic nuance improves when paid reasoning is enabled."
            ),
            strategy_assessment=(
                f"Evaluated {total} recognized deck cards against {len(candidates)} bounded owned alternatives."
            ),
            suggested_cuts=[
                CardRecommendation(
                    name=card["name"],
                    reason="High mana value or no core functional role was recognized; review this slot manually.",
                )
                for card in cuts
            ],
            suggested_additions=additions,
            strengths=strengths,
            weaknesses=weaknesses[:12],
        )
