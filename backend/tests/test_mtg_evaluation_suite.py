from __future__ import annotations

import json
from pathlib import Path

from app.mechanics.evaluation import (
    evaluate_interaction,
    profile_satisfies_expectation,
)
from app.mechanics.profile import MechanicProfile


SUITE_PATH = Path(__file__).parents[1] / "evals" / "mtg_mechanics_v1.json"


def _suite() -> dict:
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


def test_evaluation_suite_covers_required_categories() -> None:
    suite = _suite()
    categories = {
        case["category"]
        for section in ("profile_expectations", "interaction_expectations", "legality_expectations")
        for case in suite[section]
    }
    assert categories == {
        "indirect_synergy", "universal_card", "anti_synergy",
        "legality_trap", "known_interaction",
    }


def test_evaluation_suite_covers_full_pipeline_groups() -> None:
    suite = _suite()
    assert len(suite["profile_expectations"]) >= 5
    assert len(suite["interaction_expectations"]) >= 6
    assert len(suite["retrieval_expectations"]) >= 4
    assert len(suite["construction_expectations"]) >= 1
    assert len(suite["legality_expectations"]) >= 3


def test_golden_profiles_are_schema_valid_and_meet_expectations() -> None:
    suite = _suite()
    profiles = {
        key: MechanicProfile.model_validate(value)
        for key, value in suite["profiles"].items()
    }
    for expectation in suite["profile_expectations"]:
        assert profile_satisfies_expectation(
            profiles[expectation["profile"]], expectation
        ), expectation["id"]


def test_golden_interactions_match_expected_outcomes() -> None:
    suite = _suite()
    profiles = {
        key: MechanicProfile.model_validate(value)
        for key, value in suite["profiles"].items()
    }
    for expectation in suite["interaction_expectations"]:
        result = evaluate_interaction(
            profiles[expectation["left"]], profiles[expectation["right"]]
        )
        assert result.outcome == expectation["expected"], expectation["id"]
        assert set(expectation["mechanics"]) <= set(result.mechanics), expectation["id"]


def test_legality_traps_use_full_color_identity_subset_rule() -> None:
    suite = _suite()
    for case in suite["legality_expectations"]:
        actual = set(case["card_color_identity"]) <= set(case["commander_color_identity"])
        assert actual is case["legal"], case["id"]
