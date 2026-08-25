from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.enrichment.base import profile_from_record
from app.mechanics.evaluation import evaluate_interaction, profile_satisfies_expectation
from app.mechanics.profile import PROFILE_SCHEMA_VERSION, TAXONOMY_VERSION, MechanicProfile
from app.models import (
    CardPrinting,
    InventoryLine,
    MechanicProfileRecord,
    OracleCard,
    RecommendationRun,
)
from app.services.candidate_retrieval import RETRIEVAL_VERSION, retrieve_owned_candidates
from app.services.deck_optimizer import validate_optimized_deck
from app.services.recommendation_history import candidates_for_run, optimizer_for_run


SUITE_PATH = Path(__file__).parents[2] / "evals" / "mtg_mechanics_v1.json"


@lru_cache(maxsize=1)
def load_quality_suite() -> dict:
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


def _case(case_id: str, group: str, category: str, status: str, **details) -> dict:
    return {
        "id": case_id,
        "group": group,
        "category": category,
        "status": status,
        **details,
    }


def _current_profiles_by_name(db: Session) -> dict[str, MechanicProfile]:
    records = (
        db.query(MechanicProfileRecord)
        .join(OracleCard, OracleCard.oracle_id == MechanicProfileRecord.oracle_id)
        .filter(
            MechanicProfileRecord.is_current.is_(True),
            MechanicProfileRecord.schema_version == PROFILE_SCHEMA_VERSION,
            MechanicProfileRecord.taxonomy_version == TAXONOMY_VERSION,
        )
        .all()
    )
    return {record.oracle.name.casefold(): profile_from_record(record) for record in records}


def _owned_names(db: Session) -> set[str]:
    return {
        name.casefold()
        for (name,) in (
            db.query(OracleCard.name)
            .join(CardPrinting, CardPrinting.oracle_id == OracleCard.oracle_id)
            .join(InventoryLine, InventoryLine.scryfall_id == CardPrinting.scryfall_id)
            .filter(InventoryLine.quantity > 0)
            .distinct()
            .all()
        )
    }


def run_local_quality_evaluation(db: Session) -> dict:
    """Evaluate stored data and retrieval without network or model requests."""
    suite = load_quality_suite()
    golden = {
        key: MechanicProfile.model_validate(value)
        for key, value in suite["profiles"].items()
    }
    profiles = _current_profiles_by_name(db)
    owned = _owned_names(db)
    cases: list[dict] = []

    for expectation in suite["profile_expectations"]:
        expected = golden[expectation["profile"]]
        name_key = expected.card_name.casefold()
        actual = profiles.get(name_key)
        if name_key not in owned:
            cases.append(_case(
                expectation["id"], "profile", expectation["category"], "skipped",
                subject=expected.card_name, reason="Card is not currently owned.",
            ))
            continue
        if actual is None:
            cases.append(_case(
                expectation["id"], "profile", expectation["category"], "skipped",
                subject=expected.card_name, reason="Owned card has no current mechanic profile.",
            ))
            continue
        passed = profile_satisfies_expectation(actual, expectation)
        cases.append(_case(
            expectation["id"], "profile", expectation["category"],
            "passed" if passed else "failed",
            subject=expected.card_name,
            expected={
                key: expectation[key]
                for key in ("required_roles", "required_hooks", "universal_tier")
                if key in expectation
            },
            actual={
                "roles": [role.value for role in actual.roles],
                "hooks": [
                    {"verb": hook.verb.value, "mechanic": hook.mechanic.value, "scope": hook.scope.value}
                    for hook in actual.hooks
                ],
                "universal_tier": actual.universal_utility.tier.value,
            },
        ))

    for expectation in suite["interaction_expectations"]:
        left_name = golden[expectation["left"]].card_name
        right_name = golden[expectation["right"]].card_name
        left = profiles.get(left_name.casefold())
        right = profiles.get(right_name.casefold())
        missing = [
            name for name, profile in ((left_name, left), (right_name, right))
            if name.casefold() not in owned or profile is None
        ]
        if missing:
            cases.append(_case(
                expectation["id"], "interaction", expectation["category"], "skipped",
                subject=f"{left_name} + {right_name}",
                reason="Missing owned current profiles: " + ", ".join(missing),
            ))
            continue
        result = evaluate_interaction(left, right)
        passed = (
            result.outcome == expectation["expected"]
            and set(expectation["mechanics"]) <= set(result.mechanics)
        )
        cases.append(_case(
            expectation["id"], "interaction", expectation["category"],
            "passed" if passed else "failed",
            subject=f"{left_name} + {right_name}",
            expected={"outcome": expectation["expected"], "mechanics": expectation["mechanics"]},
            actual={"outcome": result.outcome, "mechanics": list(result.mechanics), "reasons": list(result.reasons)},
        ))

    for expectation in suite["retrieval_expectations"]:
        referenced = {
            *expectation.get("seed_profiles", []),
            *expectation.get("exclude_profiles", []),
            expectation["expected_profile"],
        }
        required_names = [golden[key].card_name for key in referenced]
        missing_owned = [name for name in required_names if name.casefold() not in owned]
        missing_profiles = [name for name in required_names if name.casefold() not in profiles]
        if missing_owned or missing_profiles:
            reason_parts = []
            if missing_owned:
                reason_parts.append("not owned: " + ", ".join(sorted(missing_owned)))
            if missing_profiles:
                reason_parts.append("not profiled: " + ", ".join(sorted(missing_profiles)))
            cases.append(_case(
                expectation["id"], "retrieval", expectation["category"], "skipped",
                subject=golden[expectation["expected_profile"]].card_name,
                reason="; ".join(reason_parts),
            ))
            continue
        seed_names = {golden[key].card_name for key in expectation.get("seed_profiles", [])}
        exclude_names = {golden[key].card_name for key in expectation.get("exclude_profiles", [])}
        results = retrieve_owned_candidates(
            db,
            expectation["query"],
            seed_names=seed_names,
            exclude_names=exclude_names,
            limit=200,
            allow_remote_embeddings=False,
        )
        expected_name = golden[expectation["expected_profile"]].card_name
        match = next((card for card in results if card["name"] == expected_name), None)
        rank = next((index + 1 for index, card in enumerate(results) if card["name"] == expected_name), None)
        component_value = (
            match["retrieval"]["components"].get(expectation["component"], 0)
            if match else None
        )
        passed = match is not None
        if passed and "top_n" in expectation:
            passed = rank is not None and rank <= expectation["top_n"]
        if passed and "minimum_component" in expectation:
            passed = component_value >= expectation["minimum_component"]
        if passed and "maximum_component" in expectation:
            passed = component_value <= expectation["maximum_component"]
        cases.append(_case(
            expectation["id"], "retrieval", expectation["category"],
            "passed" if passed else "failed",
            subject=expected_name,
            expected={
                key: expectation[key]
                for key in ("top_n", "component", "minimum_component", "maximum_component")
                if key in expectation
            },
            actual={
                "rank": rank,
                "component": expectation["component"],
                "component_value": component_value,
                "semantic_source": (match or {}).get("retrieval", {}).get("semantic", {}).get("source"),
            },
        ))

    for expectation in suite["legality_expectations"]:
        actual = set(expectation["card_color_identity"]) <= set(expectation["commander_color_identity"])
        cases.append(_case(
            expectation["id"], "legality", expectation["category"],
            "passed" if actual is expectation["legal"] else "failed",
            subject=expectation["card_name"],
            expected={"legal": expectation["legal"]},
            actual={"legal": actual},
        ))

    for expectation in suite.get("construction_expectations", []):
        selected_run = None
        selected_optimizer = None
        for run in db.query(RecommendationRun).order_by(RecommendationRun.created_at.desc()).all():
            try:
                optimizer = optimizer_for_run(run)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if optimizer.get("feasible"):
                selected_run = run
                selected_optimizer = optimizer
                break
        if selected_run is None or selected_optimizer is None:
            cases.append(_case(
                expectation["id"], "construction", expectation["category"], "skipped",
                subject="Latest feasible recommendation build",
                reason="No feasible recommendation run is stored yet.",
            ))
            continue
        try:
            validation = validate_optimized_deck(
                db,
                candidates_for_run(selected_run),
                selected_optimizer.get("entries", []),
            )
            passed = bool(validation["valid"])
            actual = {
                "run_id": selected_run.id,
                "provider": selected_run.provider,
                "model": selected_run.model,
                "valid": validation["valid"],
                "checks": validation["checks"],
                "errors": validation["errors"],
            }
        except Exception as exc:
            passed = False
            actual = {
                "run_id": selected_run.id,
                "valid": False,
                "errors": [{"code": "invalid_snapshot", "message": str(exc)}],
            }
        cases.append(_case(
            expectation["id"], "construction", expectation["category"],
            "passed" if passed else "failed",
            subject=f"Recommendation run {selected_run.id}",
            expected={"valid": True, "hard_constraints": "all"},
            actual=actual,
        ))

    counts = Counter(case["status"] for case in cases)
    executed = counts["passed"] + counts["failed"]
    by_category: dict[str, dict] = {}
    for category in sorted({case["category"] for case in cases}):
        category_cases = [case for case in cases if case["category"] == category]
        category_counts = Counter(case["status"] for case in category_cases)
        category_executed = category_counts["passed"] + category_counts["failed"]
        by_category[category] = {
            "passed": category_counts["passed"],
            "failed": category_counts["failed"],
            "skipped": category_counts["skipped"],
            "pass_rate": round(category_counts["passed"] / category_executed, 4) if category_executed else None,
        }
    return {
        "suite_version": suite["suite_version"],
        "profile_schema_version": suite["profile_schema_version"],
        "taxonomy_version": suite["taxonomy_version"],
        "retrieval_version": RETRIEVAL_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "network_requests": 0,
        "summary": {
            "total": len(cases),
            "passed": counts["passed"],
            "failed": counts["failed"],
            "skipped": counts["skipped"],
            "coverage": round(executed / len(cases), 4) if cases else 0,
            "pass_rate": round(counts["passed"] / executed, 4) if executed else None,
        },
        "categories": by_category,
        "cases": cases,
    }
