from __future__ import annotations

import re
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator


REVIEW_SCHEMA_VERSION = "1.0.0"
_QUANTITY_RE = re.compile(r"^\s*\d+\s+(.+?)\s*$")


class CardRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1_000)


class ReplacementRecommendation(CardRecommendation):
    replaces: str | None = Field(default=None, max_length=500)


class SuggestReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[REVIEW_SCHEMA_VERSION] = REVIEW_SCHEMA_VERSION
    theme_assessment: str = Field(min_length=1, max_length=2_000)
    suggestions: list[CardRecommendation] = Field(default_factory=list, max_length=20)
    cards_to_consider_cutting: list[CardRecommendation] = Field(default_factory=list, max_length=20)
    viability_note: str = Field(min_length=1, max_length=2_000)

    @field_validator("suggestions", "cards_to_consider_cutting")
    @classmethod
    def unique_names(cls, value: list[CardRecommendation]) -> list[CardRecommendation]:
        if len({item.name.casefold() for item in value}) != len(value):
            raise ValueError("recommendation names must be unique")
        return value


class AuditReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[REVIEW_SCHEMA_VERSION] = REVIEW_SCHEMA_VERSION
    overall_assessment: str = Field(min_length=1, max_length=1_000)
    strategy_assessment: str = Field(min_length=1, max_length=2_000)
    suggested_cuts: list[CardRecommendation] = Field(default_factory=list, max_length=20)
    suggested_additions: list[ReplacementRecommendation] = Field(default_factory=list, max_length=20)
    strengths: list[str] = Field(default_factory=list, max_length=12)
    weaknesses: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("suggested_cuts", "suggested_additions")
    @classmethod
    def unique_names(cls, value):
        if len({item.name.casefold() for item in value}) != len(value):
            raise ValueError("recommendation names must be unique")
        return value


def parse_deck_names(decklist: str) -> list[str]:
    return [name for _, name in parse_deck_entries(decklist)]


def parse_deck_entries(decklist: str) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for raw_line in decklist.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.casefold() in {
            "commander", "deck", "sideboard", "maybeboard",
        }:
            continue
        match = _QUANTITY_RE.match(line)
        if match:
            quantity_text = line.split(maxsplit=1)[0]
            entries.append((int(quantity_text), match.group(1).strip()))
        else:
            entries.append((1, line))
    return entries


@runtime_checkable
class DeckReviewProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def suggest(
        self,
        current_list: str,
        candidates: list[dict],
        theme_hint: str | None,
        existing_cards: list[dict],
    ) -> SuggestReview: ...

    def audit(
        self,
        decklist: str,
        candidates: list[dict],
        existing_cards: list[dict],
    ) -> AuditReview: ...


def _canonical_maps(candidates: list[dict], deck_names: list[str]):
    candidate_map = {str(card["name"]).casefold(): str(card["name"]) for card in candidates}
    deck_map = {name.casefold(): name for name in deck_names}
    return candidate_map, deck_map


def validate_suggest_review(
    candidates: list[dict], deck_names: list[str], review: SuggestReview
) -> SuggestReview:
    candidate_map, deck_map = _canonical_maps(candidates, deck_names)
    suggestions = [
        item.model_copy(update={"name": _bounded_name(candidate_map, item.name, "candidate pool")})
        for item in review.suggestions
    ]
    cuts = [
        item.model_copy(update={"name": _bounded_name(deck_map, item.name, "current deck")})
        for item in review.cards_to_consider_cutting
    ]
    return review.model_copy(update={"suggestions": suggestions, "cards_to_consider_cutting": cuts})


def validate_audit_review(
    candidates: list[dict], deck_names: list[str], review: AuditReview
) -> AuditReview:
    candidate_map, deck_map = _canonical_maps(candidates, deck_names)
    cuts = [
        item.model_copy(update={"name": _bounded_name(deck_map, item.name, "current deck")})
        for item in review.suggested_cuts
    ]
    additions = []
    for item in review.suggested_additions:
        replacement = (
            _bounded_name(deck_map, item.replaces, "current deck")
            if item.replaces is not None else None
        )
        additions.append(item.model_copy(update={
            "name": _bounded_name(candidate_map, item.name, "candidate pool"),
            "replaces": replacement,
        }))
    return review.model_copy(update={"suggested_cuts": cuts, "suggested_additions": additions})


def _bounded_name(canonical: dict[str, str], value: str, boundary: str) -> str:
    result = canonical.get(value.casefold())
    if result is None:
        raise ValueError(f"Review referenced {value!r} outside the {boundary}")
    return result
