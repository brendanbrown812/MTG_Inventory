from __future__ import annotations

import json

from app.reasoning.base import ReasoningProposal, validate_reasoning_proposal


def _strip_markdown_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])
    return raw.strip()


def _candidate_payload(card: dict) -> dict:
    profile = card.get("mechanic_profile") or {}
    retrieval = card.get("retrieval") or {}
    return {
        "name": card["name"],
        "mana_cost": card.get("mana_cost"),
        "mana_value": card.get("cmc"),
        "type_line": card.get("type_line"),
        "oracle_text": card.get("oracle_text"),
        "color_identity": card.get("color_identity"),
        "owned_quantity": card.get("owned_quantity", 0),
        "deterministic_roles": card.get("deterministic_roles", []),
        "structured_roles": profile.get("roles", []),
        "mechanic_hooks": [
            {key: hook[key] for key in ("verb", "mechanic", "scope", "condition")}
            for hook in profile.get("hooks", [])
        ],
        "retrieval_score": retrieval.get("total_score", 0),
        "retrieval_reasons": retrieval.get("reasons", [])[:4],
    }


class AnthropicStrategyReasoner:
    provider_name = "anthropic"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        self._api_key = api_key
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def propose(
        self,
        theme: str,
        candidates: list[dict],
        commander_name: str | None,
    ) -> ReasoningProposal:
        import anthropic

        schema = ReasoningProposal.model_json_schema()
        payload = {
            "theme": theme,
            "preferred_commander": commander_name,
            "candidate_count": len(candidates),
            "candidates": [_candidate_payload(card) for card in candidates],
            "output_schema": schema,
        }
        system = (
            "You are the strategic reasoning stage of a Commander deck builder. "
            "The candidate list is a closed universe. Propose coherent packages and priorities "
            "using only exact candidate names. Do not produce a decklist or quantities. "
            "Account for curve, interaction, ramp, draw, mana, anti-synergies, and package overlap. "
            "Code will make every final card choice and enforce all format constraints. "
            "Return only a JSON object matching the supplied schema."
        )
        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=4_000,
            system=system,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        proposal = ReasoningProposal.model_validate_json(
            _strip_markdown_json(response.content[0].text)
        )
        return validate_reasoning_proposal(candidates, proposal)
