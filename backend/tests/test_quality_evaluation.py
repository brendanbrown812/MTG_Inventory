from __future__ import annotations

import json
from pathlib import Path

from app.database import SessionLocal
from app.evaluation.runner import run_local_quality_evaluation
from app.mechanics.profile import MechanicProfile
from app.models import CardPrinting, InventoryLine, MechanicProfileRecord, OracleCard


_SUITE = json.loads(
    (Path(__file__).parents[1] / "evals" / "mtg_mechanics_v1.json").read_text(encoding="utf-8")
)


def _add_golden_collection(db) -> None:
    for key, raw_profile in _SUITE["profiles"].items():
        profile = MechanicProfile.model_validate(raw_profile)
        type_line = "Artifact"
        if key in {"fynn", "muldrotha", "chatterfang"}:
            type_line = "Legendary Creature"
        elif key in {"goblin_sharpshooter", "pitiless_plunderer"}:
            type_line = "Creature"
        oracle_text = "\n".join(dict.fromkeys(hook.evidence for hook in profile.hooks))
        db.add(OracleCard(
            oracle_id=profile.oracle_id,
            name=profile.card_name,
            type_line=type_line,
            oracle_text=oracle_text,
            color_identity="[]",
            legalities_json=json.dumps({"commander": "legal"}),
            keywords="[]",
        ))
        printing_id = f"quality-{key}"
        db.add(CardPrinting(scryfall_id=printing_id, oracle_id=profile.oracle_id))
        db.add(InventoryLine(scryfall_id=printing_id, quantity=1))
        db.add(MechanicProfileRecord(
            oracle_id=profile.oracle_id,
            schema_version=profile.schema_version,
            taxonomy_version=profile.taxonomy_version,
            profile_json=profile.model_dump_json(),
            provider="golden-fixture",
            model="quality-v1",
            confidence=profile.confidence,
            is_current=True,
        ))


def test_quality_gate_reports_coverage_instead_of_failing_missing_collection_cases() -> None:
    with SessionLocal() as db:
        report = run_local_quality_evaluation(db)

    assert report["network_requests"] == 0
    assert report["summary"] == {
        "total": 19,
        "passed": 3,
        "failed": 0,
        "skipped": 16,
        "coverage": 0.1579,
        "pass_rate": 1.0,
    }
    assert {case["group"] for case in report["cases"]} == {
        "profile", "interaction", "retrieval", "legality", "construction",
    }


def test_complete_golden_collection_passes_every_quality_case() -> None:
    with SessionLocal() as db:
        _add_golden_collection(db)
        db.commit()
        report = run_local_quality_evaluation(db)

    incomplete = [case for case in report["cases"] if case["status"] != "passed"]
    assert len(incomplete) == 1
    assert incomplete[0]["group"] == "construction"
    assert incomplete[0]["status"] == "skipped"
    assert report["summary"] == {
        "total": 19,
        "passed": 18,
        "failed": 0,
        "skipped": 1,
        "coverage": 0.9474,
        "pass_rate": 1.0,
    }
    retrieval_cases = [case for case in report["cases"] if case["group"] == "retrieval"]
    assert len(retrieval_cases) == 4
    assert all(case["actual"]["semantic_source"] == "lexical_fallback" for case in retrieval_cases)


def test_quality_endpoint_is_read_only_and_reports_versions(client) -> None:
    response = client.get("/api/evaluations/mtg-quality")
    assert response.status_code == 200
    payload = response.json()
    assert payload["suite_version"] == "1.0.0"
    assert payload["profile_schema_version"] == "1.0.0"
    assert payload["taxonomy_version"] == "2026.1"
    assert payload["network_requests"] == 0
