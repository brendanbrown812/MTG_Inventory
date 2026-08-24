"""
Claude adapter used only for Commander generation and deck review.

─── Checking tagging quality after a batch ───────────────────────────────────
─── Switching models ─────────────────────────────────────────────────────────
─── Adding a new model ───────────────────────────────────────────────────────
"""

import json

from app.config import settings

def _get_client():
    import anthropic  # lazy import so the module loads even without the package installed
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to backend/.env.")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _strip_markdown_json(raw: str) -> str:
    """Strip optional ```json ... ``` fences Claude sometimes adds."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        inner = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
        raw = "\n".join(inner)
    return raw.strip()


# ─── Synergy Tagging ─────────────────────────────────────────────────────────

# ─── Deckbuilding ─────────────────────────────────────────────────────────────

def _format_pool(cards: list[dict]) -> str:
    lines = []
    for c in cards:
        cost   = c.get("mana_cost") or ""
        oracle = (c.get("oracle_text") or "").replace("\n", " ")[:280]
        profile = c.get("mechanic_profile") or {}
        roles = ",".join(profile.get("roles", [])) or "none"
        hooks = ",".join(
            f"{hook['verb']}:{hook['mechanic']}"
            for hook in profile.get("hooks", [])[:8]
        ) or "none"
        universal = profile.get("universal_utility", {}).get("tier", "none")
        retrieval = c.get("retrieval") or {}
        score = retrieval.get("total_score", 0)
        components = retrieval.get("components", {})
        score_text = ",".join(
            f"{key}={value}" for key, value in components.items() if value
        ) or "none"
        score_reasons = "; ".join(retrieval.get("reasons", [])[:3]) or "none"
        lines.append(
            f"- {c['name']} {cost} | {c.get('type_line') or ''} | "
            f"owned={c.get('owned_quantity', 0)} | relevance={score} ({score_text}) | "
            f"why={score_reasons} | roles={roles} | hooks={hooks} | "
            f"universal={universal} | {oracle}"
        )
    return "\n".join(lines)


_SUGGEST_SCHEMA = """{
  "theme_assessment": "What strategies the current deck is pursuing",
  "suggestions": [
    {"name": "Card Name", "reason": "Why it fits and what it does for the deck"}
  ],
  "cards_to_consider_cutting": [
    {"name": "Card Name", "reason": "Why it underperforms relative to suggestions"}
  ],
  "viability_note": "Overall assessment of direction and how well your collection supports it"
}"""

_AUDIT_SCHEMA = """{
  "overall_assessment": "Grade and brief verdict (e.g. B+ — solid engine but curve is top-heavy)",
  "strategy_assessment": "What this deck is trying to do and how coherent it is",
  "suggested_cuts": [
    {"name": "Card Name", "reason": "Why it underperforms"}
  ],
  "suggested_additions": [
    {"name": "Card Name", "replaces": "Card to cut or null", "reason": "Why this improves the deck"}
  ],
  "strengths": ["Strength 1", "Strength 2"],
  "weaknesses": ["Weakness 1", "Weakness 2"]
}"""

_DECK_SYSTEM = (
    "You are an expert Magic: The Gathering Commander deckbuilder with deep knowledge of "
    "synergies, power levels, and format rules. Be specific and honest — "
    "if a collection can't support a good deck around a theme, say so clearly."
)


def suggest_additions(
    current_list: str,
    pool: list[dict],
    theme_hint: str | None,
) -> dict:
    """Suggest pool cards that would strengthen an in-progress deck."""
    client    = _get_client()
    pool_text = _format_pool(pool)
    theme_line = f"\nFocused on: {theme_hint}" if theme_hint else ""
    line_count = len([l for l in current_list.strip().splitlines() if l.strip()])

    prompt = (
        f"I'm building a Commander deck and need addition suggestions from my collection.{theme_line}\n\n"
        f"Current deck ({line_count} lines):\n{current_list}\n\n"
        f"Available cards from my collection (Commander-legal, thematically relevant):\n{pool_text}\n\n"
        f"Suggest the best additions from the available pool.\nReturn ONLY valid JSON:\n{_SUGGEST_SCHEMA}"
    )

    response = client.messages.create(
        model=settings.deckbuilding_model,
        max_tokens=3000,
        system=_DECK_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(_strip_markdown_json(response.content[0].text))


def audit_deck(decklist: str, pool: list[dict]) -> dict:
    """Audit a complete deck and suggest cuts/additions from pool."""
    client    = _get_client()
    pool_text = _format_pool(pool)

    prompt = (
        f"Audit this Commander deck and suggest improvements from my collection.\n\n"
        f"Current deck:\n{decklist}\n\n"
        f"Cards I own that could improve this deck (not already in the deck):\n{pool_text}\n\n"
        f"Provide an honest critique with specific cuts and additions.\nReturn ONLY valid JSON:\n{_AUDIT_SCHEMA}"
    )

    response = client.messages.create(
        model=settings.deckbuilding_model,
        max_tokens=3000,
        system=_DECK_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(_strip_markdown_json(response.content[0].text))
