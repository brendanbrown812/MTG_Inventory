from __future__ import annotations

from sqlalchemy.orm import Session

from app.reasoning.base import StrategyReasoner, validate_reasoning_proposal
from app.services.deck_optimizer import optimize_commander_deck


def build_deck_with_reasoning(
    db: Session,
    *,
    theme: str,
    candidates: list[dict],
    commander_name: str | None,
    reasoner: StrategyReasoner,
) -> dict:
    """Run advisory reasoning, then deterministic assembly and validation."""
    raw_proposal = reasoner.propose(theme, candidates, commander_name)
    proposal = validate_reasoning_proposal(candidates, raw_proposal)
    optimized = optimize_commander_deck(db, candidates, proposal, commander_name)

    package_failures = [
        package for package in optimized["package_report"]
        if not package["minimum_satisfied"]
    ]
    if not optimized["feasible"]:
        viability = "insufficient"
        viability_note = (
            "The bounded owned-card pool could not satisfy every hard Commander and "
            "collection constraint. No model-authored fallback deck was accepted."
        )
    elif package_failures:
        viability = "playable"
        viability_note = (
            "The optimizer produced a legal owned deck, but some proposed strategic "
            "packages could not reach their requested minimums."
        )
    else:
        viability = "strong"
        viability_note = (
            "The optimizer produced a legal, fully owned 100-card deck and satisfied "
            "the proposed package minimums."
        )

    warnings = [
        f"Package minimum not met: {package['name']} "
        f"({package['included_count']}/{package['minimum_cards']})."
        for package in package_failures
    ]
    warnings.extend(
        f"Hard constraint failed: {error['code']}"
        for error in optimized["validation"]["errors"]
    )
    result = {
        "viability": viability,
        "viability_note": viability_note,
        "commander": optimized["commander"],
        "reasoning": proposal.strategy_summary,
        "decklist": optimized["decklist"],
        "key_synergies": [
            f"{package.name}: {package.purpose}" for package in proposal.packages
        ],
        "missing_staples": [],
        "strategic_packages": [package.model_dump(mode="json") for package in proposal.packages],
        "reasoning_proposal": proposal.model_dump(mode="json"),
        "reasoning_provenance": {
            "provider": reasoner.provider_name,
            "model": reasoner.model_name,
            "schema_version": proposal.schema_version,
        },
        "optimizer": optimized,
    }
    return {"result": result, "warnings": warnings}
