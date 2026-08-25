from __future__ import annotations

import json

from app.enrichment.base import (
    EnrichmentBatch,
    EnrichmentCard,
    ProviderUsage,
)
from app.mechanics.profile import MechanicProfile


def _strip_markdown_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])
    return raw.strip()


class AnthropicEnrichmentProvider:
    provider_name = "anthropic"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        self._api_key = api_key
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def enrich(self, cards: list[EnrichmentCard]) -> EnrichmentBatch:
        import anthropic

        schema = MechanicProfile.model_json_schema()
        card_payload = [
            {
                "oracle_id": card.oracle_id,
                "name": card.name,
                "type_line": card.type_line,
                "mana_cost": card.mana_cost,
                "oracle_text": card.oracle_text,
                "scryfall_keywords": list(card.keywords),
            }
            for card in cards
        ]
        system = (
            "You produce evidence-backed Magic: The Gathering mechanic profiles. "
            "Use only enum values allowed by the JSON schema. Classify what the card "
            "produces, consumes, rewards, enables, grants, amplifies, prevents, or replaces. "
            "Capture indirect effects such as granting deathtouch; do not infer a theme from "
            "the card name. Evidence must be an exact contiguous excerpt of Oracle text. "
            "Universal utility means broad infrastructure such as efficient mana, not merely "
            "a strong card. Return one profile for every input card and no others."
        )
        prompt = json.dumps({
            "task": "Return JSON object with key profiles containing the profile array.",
            "profile_json_schema": schema,
            "cards": card_payload,
        })
        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=max(2048, len(cards) * 700),
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _strip_markdown_json(response.content[0].text)
        payload = json.loads(raw)
        profiles = tuple(
            MechanicProfile.model_validate(item) for item in payload.get("profiles", [])
        )
        batch = EnrichmentBatch(
            profiles=profiles,
            usage=ProviderUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
        )
        return batch
