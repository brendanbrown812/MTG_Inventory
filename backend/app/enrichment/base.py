from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.mechanics.profile import MechanicProfile
from app.models import MechanicProfileRecord


@dataclass(frozen=True)
class EnrichmentCard:
    oracle_id: str
    name: str
    type_line: str | None
    oracle_text: str | None
    mana_cost: str | None
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class EnrichmentBatch:
    profiles: tuple[MechanicProfile, ...]
    usage: ProviderUsage = ProviderUsage()


@runtime_checkable
class EnrichmentProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def enrich(self, cards: list[EnrichmentCard]) -> EnrichmentBatch: ...


def _normalize_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def validate_provider_batch(
    cards: list[EnrichmentCard], batch: EnrichmentBatch
) -> tuple[MechanicProfile, ...]:
    expected = {card.oracle_id: card for card in cards}
    actual = {profile.oracle_id: profile for profile in batch.profiles}
    if len(actual) != len(batch.profiles):
        raise ValueError("Provider returned duplicate Oracle IDs")
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise ValueError(f"Provider card set mismatch: missing={missing}, extra={extra}")

    for oracle_id, profile in actual.items():
        card = expected[oracle_id]
        if profile.card_name != card.name:
            raise ValueError(
                f"Provider changed card name for {oracle_id}: {profile.card_name!r} != {card.name!r}"
            )
        oracle_text = _normalize_evidence(card.oracle_text or "")
        for hook in profile.hooks:
            evidence = _normalize_evidence(hook.evidence)
            if evidence not in oracle_text:
                raise ValueError(
                    f"Evidence for {card.name} is not present in Oracle text: {hook.evidence!r}"
                )
    return tuple(actual[card.oracle_id] for card in cards)


def partition_provider_batch(
    cards: list[EnrichmentCard], batch: EnrichmentBatch
) -> tuple[tuple[MechanicProfile, ...], dict[str, str]]:
    """Keep independently valid profiles instead of losing a paid batch to one bad card."""
    expected = {card.oracle_id: card for card in cards}
    grouped: dict[str, list[MechanicProfile]] = defaultdict(list)
    failures: dict[str, str] = {}
    for profile in batch.profiles:
        grouped[profile.oracle_id].append(profile)
        if profile.oracle_id not in expected:
            failures[f"extra:{profile.oracle_id}"] = "Provider returned an unexpected Oracle ID"

    valid: list[MechanicProfile] = []
    for card in cards:
        profiles = grouped.get(card.oracle_id, [])
        if not profiles:
            failures[card.oracle_id] = f"Provider omitted {card.name}"
            continue
        if len(profiles) > 1:
            failures[card.oracle_id] = f"Provider returned {card.name} more than once"
            continue
        profile = profiles[0]
        if profile.card_name != card.name:
            failures[card.oracle_id] = (
                f"Provider changed card name: {profile.card_name!r} != {card.name!r}"
            )
            continue
        oracle_text = _normalize_evidence(card.oracle_text or "")
        invalid_hook = next(
            (
                hook for hook in profile.hooks
                if _normalize_evidence(hook.evidence) not in oracle_text
            ),
            None,
        )
        if invalid_hook is not None:
            failures[card.oracle_id] = (
                f"Evidence for {card.name} is not present in Oracle text: "
                f"{invalid_hook.evidence!r}"
            )
            continue
        valid.append(profile)
    return tuple(valid), failures


def persist_profile_batch(
    db: Session,
    provider: EnrichmentProvider,
    batch: EnrichmentBatch,
) -> list[MechanicProfileRecord]:
    records: list[MechanicProfileRecord] = []
    profile_count = max(1, len(batch.profiles))
    input_tokens_per_profile = round(batch.usage.input_tokens / profile_count)
    output_tokens_per_profile = round(batch.usage.output_tokens / profile_count)
    for profile in batch.profiles:
        db.query(MechanicProfileRecord).filter(
            MechanicProfileRecord.oracle_id == profile.oracle_id,
            MechanicProfileRecord.is_current.is_(True),
        ).update({MechanicProfileRecord.is_current: False}, synchronize_session=False)
        record = MechanicProfileRecord(
            oracle_id=profile.oracle_id,
            schema_version=profile.schema_version,
            taxonomy_version=profile.taxonomy_version,
            profile_json=profile.model_dump_json(),
            provider=provider.provider_name,
            model=provider.model_name,
            confidence=profile.confidence,
            is_current=True,
            input_tokens=input_tokens_per_profile,
            output_tokens=output_tokens_per_profile,
        )
        db.add(record)
        records.append(record)
    db.flush()
    return records


def profile_from_record(record: MechanicProfileRecord) -> MechanicProfile:
    return MechanicProfile.model_validate_json(record.profile_json)


def card_to_provider_input(card: Any) -> EnrichmentCard:
    try:
        keywords = json.loads(card.keywords or "[]")
    except (json.JSONDecodeError, TypeError):
        keywords = []
    return EnrichmentCard(
        oracle_id=card.oracle_id,
        name=card.name,
        type_line=card.type_line,
        oracle_text=card.oracle_text,
        mana_cost=card.mana_cost,
        keywords=tuple(str(keyword) for keyword in keywords),
    )
