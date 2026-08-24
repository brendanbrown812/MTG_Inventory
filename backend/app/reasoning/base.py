from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


REASONING_SCHEMA_VERSION = "1.0.0"


class StrategyPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=500)
    card_names: list[str] = Field(min_length=1, max_length=24)
    priority: float = Field(ge=0, le=1)
    minimum_cards: int = Field(default=1, ge=0, le=24)
    maximum_cards: int = Field(default=8, ge=1, le=24)

    @field_validator("card_names")
    @classmethod
    def unique_card_names(cls, value: list[str]) -> list[str]:
        if len({name.casefold() for name in value}) != len(value):
            raise ValueError("package card names must be unique")
        return value

    @model_validator(mode="after")
    def valid_bounds(self) -> "StrategyPackage":
        if self.minimum_cards > self.maximum_cards:
            raise ValueError("minimum_cards cannot exceed maximum_cards")
        if self.minimum_cards > len(self.card_names):
            raise ValueError("minimum_cards cannot exceed the proposed card count")
        return self


class ReasoningProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[REASONING_SCHEMA_VERSION] = REASONING_SCHEMA_VERSION
    strategy_summary: str = Field(min_length=1, max_length=2_000)
    recommended_commander: str | None = Field(default=None, max_length=500)
    packages: list[StrategyPackage] = Field(default_factory=list, max_length=12)
    card_priorities: dict[str, float] = Field(default_factory=dict, max_length=200)

    @field_validator("card_priorities")
    @classmethod
    def valid_priorities(cls, value: dict[str, float]) -> dict[str, float]:
        if any(priority < 0 or priority > 1 for priority in value.values()):
            raise ValueError("card priorities must be between zero and one")
        return value


@runtime_checkable
class StrategyReasoner(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def propose(
        self,
        theme: str,
        candidates: list[dict],
        commander_name: str | None,
    ) -> ReasoningProposal: ...


def validate_reasoning_proposal(
    candidates: list[dict], proposal: ReasoningProposal
) -> ReasoningProposal:
    """Canonicalize names and reject anything outside the bounded pool."""
    canonical = {card["name"].casefold(): card["name"] for card in candidates}

    def candidate_name(value: str) -> str:
        name = canonical.get(value.casefold())
        if name is None:
            raise ValueError(f"Reasoning proposal referenced a card outside the candidate pool: {value}")
        return name

    commander = (
        candidate_name(proposal.recommended_commander)
        if proposal.recommended_commander else None
    )
    packages = [
        package.model_copy(update={
            "card_names": [candidate_name(name) for name in package.card_names]
        })
        for package in proposal.packages
    ]
    priorities: dict[str, float] = {}
    for name, priority in proposal.card_priorities.items():
        priorities[candidate_name(name)] = priority
    return proposal.model_copy(update={
        "recommended_commander": commander,
        "packages": packages,
        "card_priorities": priorities,
    })
