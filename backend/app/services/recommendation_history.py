from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import (
    RecommendationCardPreference,
    RecommendationFeedback,
    RecommendationRun,
)


OUTCOMES = {"saved", "edited", "accepted", "rejected"}


def _slim_candidate(card: dict) -> dict:
    return {
        key: card.get(key)
        for key in (
            "scryfall_id", "oracle_id", "name", "mana_cost", "cmc", "type_line",
            "oracle_text", "color_identity", "keywords", "owned_quantity",
            "deterministic_roles", "mechanic_profile", "retrieval",
        )
    }


def create_recommendation_run(
    db: Session,
    *,
    query_text: str,
    requested_commander: str | None,
    provider: str,
    model: str,
    proposal: dict,
    optimizer: dict,
    candidates: list[dict],
) -> RecommendationRun:
    run = RecommendationRun(
        id=str(uuid.uuid4()),
        mode="build",
        query_text=query_text,
        requested_commander=requested_commander,
        provider=provider,
        model=model,
        proposal_json=json.dumps(proposal),
        optimizer_json=json.dumps(optimizer),
        candidate_pool_json=json.dumps([_slim_candidate(card) for card in candidates]),
    )
    db.add(run)
    db.flush()
    return run


def candidates_for_run(run: RecommendationRun) -> list[dict]:
    value = json.loads(run.candidate_pool_json)
    if not isinstance(value, list):
        raise ValueError("Recommendation candidate snapshot is invalid")
    return value


def optimizer_for_run(run: RecommendationRun) -> dict:
    value = json.loads(run.optimizer_json)
    if not isinstance(value, dict):
        raise ValueError("Recommendation optimizer snapshot is invalid")
    return value


def _quantities(entries: list[dict]) -> dict[str, int]:
    result: dict[str, int] = {}
    for entry in entries:
        oracle_id = str(entry["oracle_id"])
        result[oracle_id] = result.get(oracle_id, 0) + int(entry["quantity"])
    return result


def _update_preference(db: Session, oracle_id: str, *, accepted: int = 0, rejected: int = 0) -> None:
    preference = db.get(RecommendationCardPreference, oracle_id)
    if preference is None:
        preference = RecommendationCardPreference(
            oracle_id=oracle_id,
            accepted_count=0,
            rejected_count=0,
        )
        db.add(preference)
    preference.accepted_count = (preference.accepted_count or 0) + accepted
    preference.rejected_count = (preference.rejected_count or 0) + rejected
    preference.updated_at = datetime.now(UTC).replace(tzinfo=None)


def record_recommendation_feedback(
    db: Session,
    *,
    run: RecommendationRun,
    outcome: str,
    rating: int | None,
    notes: str | None,
    edited_entries: list[dict],
    saved_deck_id: int | None = None,
) -> RecommendationFeedback:
    if outcome not in OUTCOMES:
        raise ValueError(f"Unsupported feedback outcome: {outcome}")
    original_entries = optimizer_for_run(run).get("entries", [])
    original = _quantities(original_entries)
    edited = _quantities(edited_entries)
    all_ids = set(original) | set(edited)
    added = {
        oracle_id: edited.get(oracle_id, 0) - original.get(oracle_id, 0)
        for oracle_id in all_ids if edited.get(oracle_id, 0) > original.get(oracle_id, 0)
    }
    removed = {
        oracle_id: original.get(oracle_id, 0) - edited.get(oracle_id, 0)
        for oracle_id in all_ids if original.get(oracle_id, 0) > edited.get(oracle_id, 0)
    }

    if outcome in {"saved", "accepted"}:
        for oracle_id in edited:
            _update_preference(db, oracle_id, accepted=1)
    elif outcome == "rejected":
        for oracle_id in original:
            _update_preference(db, oracle_id, rejected=1)
    else:
        for oracle_id in added:
            _update_preference(db, oracle_id, accepted=1)
        for oracle_id in removed:
            _update_preference(db, oracle_id, rejected=1)

    feedback = RecommendationFeedback(
        run_id=run.id,
        outcome=outcome,
        rating=rating,
        notes=notes.strip() if notes and notes.strip() else None,
        edited_entries_json=json.dumps(edited_entries),
        added_or_increased_json=json.dumps(added),
        removed_or_decreased_json=json.dumps(removed),
        saved_deck_id=saved_deck_id,
    )
    db.add(feedback)
    db.flush()
    return feedback
