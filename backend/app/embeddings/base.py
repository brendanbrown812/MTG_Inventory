from __future__ import annotations

import hashlib
import math
from array import array
from dataclasses import dataclass
from typing import Protocol

from app.enrichment.base import profile_from_record
from app.models import MechanicProfileRecord, OracleCard


SEMANTIC_INDEX_VERSION = "1.0.0"


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...]
    input_tokens: int = 0


class EmbeddingProvider(Protocol):
    provider_name: str

    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: list[str]) -> EmbeddingBatch: ...


def card_embedding_text(
    card: OracleCard,
    profile_record: MechanicProfileRecord | None = None,
) -> str:
    """Stable, instruction-free document representing a card's game behavior."""
    fields = [
        f"Card: {card.name}",
        f"Type: {card.type_line or ''}",
        f"Mana cost: {card.mana_cost or ''}",
        f"Rules: {card.oracle_text or ''}",
        f"Keywords: {card.keywords or '[]'}",
    ]
    if profile_record is not None:
        profile = profile_from_record(profile_record)
        fields.extend((
            "Functional roles: " + ", ".join(role.value for role in profile.roles),
            "Mechanic relationships: " + "; ".join(
                f"{hook.verb.value} {hook.mechanic.value} when {hook.condition.value} "
                f"for {hook.scope.value}"
                for hook in profile.hooks
            ),
            "Universal utility: " + profile.universal_utility.tier.value + " "
            + ", ".join(reason.value for reason in profile.universal_utility.reasons),
            f"Profile schema: {profile.schema_version}/{profile.taxonomy_version}",
        ))
    return "\n".join(fields)


def query_embedding_text(query_text: str) -> str:
    return "Magic: The Gathering Commander deck strategy request:\n" + query_text.strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_vector(values: list[float] | tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(float(value) ** 2 for value in values))
    if not norm:
        raise ValueError("Embedding vector cannot be all zeroes")
    return tuple(float(value) / norm for value in values)


def encode_vector(values: list[float] | tuple[float, ...]) -> bytes:
    normalized = normalize_vector(values)
    result = array("f", normalized)
    if result.itemsize != 4:
        raise RuntimeError("Platform float array is not 32-bit")
    return result.tobytes()


def decode_vector(payload: bytes, dimensions: int) -> tuple[float, ...]:
    result = array("f")
    result.frombytes(payload)
    if len(result) != dimensions:
        raise ValueError(
            f"Stored embedding has {len(result)} dimensions; expected {dimensions}"
        )
    return tuple(result)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimensions do not match")
    # Stored vectors are normalized. Clamp small float32 rounding errors.
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right))))
