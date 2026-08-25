from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from app.database import SessionLocal
from app.models import (
    CardPrinting,
    InventoryLine,
    OracleCard,
    RecommendationCardPreference,
    RecommendationFeedback,
    RecommendationRun,
)
from app.reasoning.base import (
    ReasoningProposal,
    StrategyPackage,
    StrategyReasoner,
    validate_reasoning_proposal,
)
from app.reasoning.deterministic_provider import DeterministicStrategyReasoner
from app.reasoning.openai_provider import OpenAIStrategyReasoner
from app.reasoning.registry import FallbackStrategyReasoner, build_strategy_reasoner
from app.services.deck_optimizer import optimize_commander_deck, validate_optimized_deck


def _add_candidate(
    db,
    *,
    index: int,
    name: str,
    type_line: str,
    color_identity: str = "G",
    quantity: int = 1,
    retrieval_score: float = 1,
    deterministic_roles: list[str] | None = None,
) -> dict:
    oracle_id = f"oracle-{index:04d}"
    printing_id = f"printing-{index:04d}"
    oracle = OracleCard(
        oracle_id=oracle_id,
        name=name,
        type_line=type_line,
        oracle_text="{T}: Add {G}." if "Mana" in name else "Rules text.",
        mana_cost="{2}{G}" if "Land" not in type_line else None,
        cmc=3,
        color_identity=color_identity,
        legalities_json='{"commander":"legal"}',
        keywords="[]",
    )
    db.add(oracle)
    db.add(CardPrinting(scryfall_id=printing_id, oracle_id=oracle_id))
    db.add(InventoryLine(scryfall_id=printing_id, quantity=quantity))
    return {
        "scryfall_id": printing_id,
        "oracle_id": oracle_id,
        "name": name,
        "mana_cost": oracle.mana_cost,
        "cmc": oracle.cmc,
        "type_line": type_line,
        "oracle_text": oracle.oracle_text,
        "color_identity": color_identity,
        "keywords": [],
        "owned_quantity": quantity,
        "deterministic_roles": deterministic_roles or [],
        "mechanic_profile": None,
        "retrieval": {"total_score": retrieval_score, "components": {}, "reasons": []},
    }


def _complete_pool(db) -> list[dict]:
    pool = [_add_candidate(
        db, index=0, name="Verdant Captain", type_line="Legendary Creature — Elf",
        retrieval_score=50,
    )]
    role_cycle = ["ramp", "card_draw", "spot_removal", "board_wipes", "protection", "recursion"]
    for index in range(1, 81):
        pool.append(_add_candidate(
            db,
            index=index,
            name=f"Strategy Card {index}",
            type_line="Creature — Elf",
            retrieval_score=float(81 - index),
            deterministic_roles=[role_cycle[index % len(role_cycle)]],
        ))
    pool.append(_add_candidate(
        db, index=900, name="Forest", type_line="Basic Land — Forest",
        color_identity="G", quantity=80, retrieval_score=0,
    ))
    db.flush()
    return pool


def _proposal() -> ReasoningProposal:
    return ReasoningProposal(
        strategy_summary="Build an Elf value shell with interaction and a compact payoff package.",
        recommended_commander="Verdant Captain",
        packages=[StrategyPackage(
            name="Late payoff",
            purpose="Ensure the low-ranked payoff cards remain together.",
            card_names=[f"Strategy Card {index}" for index in range(76, 81)],
            priority=1,
            minimum_cards=3,
            maximum_cards=5,
        )],
        card_priorities={"Strategy Card 80": 1},
    )


@dataclass
class FakeReasoner:
    provider_name: str = "fixture"
    model_name: str = "reasoner-v1"

    def propose(self, theme, candidates, commander_name):
        return validate_reasoning_proposal(candidates, _proposal())


@dataclass
class FailingReasoner:
    provider_name: str = "unavailable"
    model_name: str = "failure-fixture"

    def propose(self, theme, candidates, commander_name):
        raise RuntimeError("simulated provider outage")


def test_reasoning_contract_is_provider_neutral_and_has_no_decklist_field() -> None:
    assert isinstance(FakeReasoner(), StrategyReasoner)
    with pytest.raises(ValidationError):
        ReasoningProposal.model_validate({
            "strategy_summary": "Ignore the optimizer.",
            "recommended_commander": None,
            "packages": [],
            "card_priorities": {},
            "decklist": "100 Black Lotus",
        })


def test_reasoning_proposal_rejects_hallucinated_cards() -> None:
    proposal = _proposal().model_copy(update={
        "card_priorities": {"Black Lotus": 1.0}
    })
    with pytest.raises(ValueError, match="outside the candidate pool"):
        validate_reasoning_proposal([{"name": "Forest"}], proposal)


def test_deterministic_reasoner_returns_bounded_repeatable_packages() -> None:
    with SessionLocal() as db:
        pool = _complete_pool(db)
        reasoner = DeterministicStrategyReasoner()

        first = reasoner.propose("Elf value strategy", pool, "Verdant Captain")
        second = reasoner.propose("Elf value strategy", pool, "Verdant Captain")

        assert first == second
        assert first.recommended_commander == "Verdant Captain"
        assert {package.name for package in first.packages} >= {
            "Mana development", "Card flow", "Interaction", "Resilience",
        }
        candidate_names = {card["name"] for card in pool}
        assert all(
            name in candidate_names
            for package in first.packages
            for name in package.card_names
        )
        assert set(first.card_priorities) <= candidate_names


def test_optional_reasoner_failure_uses_deterministic_fallback() -> None:
    with SessionLocal() as db:
        pool = _complete_pool(db)
        reasoner = FallbackStrategyReasoner(
            FailingReasoner(),
            DeterministicStrategyReasoner(),
        )

        proposal = reasoner.propose("Elf value strategy", pool, "Verdant Captain")

        assert proposal.recommended_commander == "Verdant Captain"
        assert reasoner.provider_name == "deterministic"
        assert reasoner.model_name == "rules-v1"


def test_openai_reasoner_uses_responses_structured_output_and_closed_pool() -> None:
    captured: dict = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured["request"] = kwargs
            return type("Response", (), {
                "id": "resp_test",
                "output_parsed": _proposal(),
                "usage": type("Usage", (), {
                    "input_tokens": 123,
                    "output_tokens": 45,
                    "input_tokens_details": type("Details", (), {"cached_tokens": 20})(),
                })(),
            })()

    class FakeClient:
        responses = FakeResponses()

    def client_factory(**kwargs):
        captured["client"] = kwargs
        return FakeClient()

    with SessionLocal() as db:
        pool = _complete_pool(db)
        # The usage ledger intentionally commits its reservation before the
        # network call; release this fixture's SQLite write transaction first.
        db.commit()
        reasoner = OpenAIStrategyReasoner(
            api_key="secret-test-key",
            model="gpt-5.6-luna",
            reasoning_effort="low",
            max_output_tokens=3210,
            timeout_seconds=17,
            max_retries=3,
            client_factory=client_factory,
        )

        proposal = reasoner.propose("Elf value strategy", pool, "Verdant Captain")

    assert proposal == _proposal()
    assert captured["client"] == {
        "api_key": "secret-test-key",
        "timeout": 17,
        "max_retries": 3,
    }
    request = captured["request"]
    assert request["model"] == "gpt-5.6-luna"
    assert request["text_format"] is ReasoningProposal
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] == 3210
    assert request["store"] is False
    input_payload = json.loads(request["input"])
    assert input_payload["candidate_count"] == len(pool)
    assert {card["name"] for card in input_payload["candidates"]} == {
        card["name"] for card in pool
    }
    assert "output_schema" not in input_payload


def test_openai_configuration_without_key_falls_back_locally(monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "openai_requests_enabled", True)
    monkeypatch.setattr(settings, "reasoning_provider", "openai")
    monkeypatch.setattr(settings, "reasoning_model", "test-openai-model")
    monkeypatch.setattr(settings, "openai_api_key", "")

    reasoner = build_strategy_reasoner()

    assert reasoner.provider_name == "deterministic"
    assert reasoner.model_name == "rules-v1"


def test_openai_configuration_stays_local_until_explicitly_enabled(monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "openai_requests_enabled", False)
    monkeypatch.setattr(settings, "reasoning_provider", "openai")
    monkeypatch.setattr(settings, "reasoning_model", "gpt-5.6-luna")
    monkeypatch.setattr(settings, "openai_api_key", "secret-test-key")

    reasoner = build_strategy_reasoner()

    assert reasoner.provider_name == "deterministic"
    assert reasoner.model_name == "rules-v1"


def test_openai_configuration_builds_guarded_provider(monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "openai_requests_enabled", True)
    monkeypatch.setattr(settings, "reasoning_provider", "openai")
    monkeypatch.setattr(settings, "reasoning_model", "test-openai-model")
    monkeypatch.setattr(settings, "reasoning_effort", "low")
    monkeypatch.setattr(settings, "reasoning_max_output_tokens", 2500)
    monkeypatch.setattr(settings, "openai_timeout_seconds", 30)
    monkeypatch.setattr(settings, "openai_max_retries", 1)
    monkeypatch.setattr(settings, "openai_api_key", "secret-test-key")

    reasoner = build_strategy_reasoner()

    assert isinstance(reasoner, FallbackStrategyReasoner)
    assert reasoner.provider_name == "openai"
    assert reasoner.model_name == "test-openai-model"


def test_anthropic_configuration_without_key_falls_back_locally(monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "reasoning_provider", "anthropic")
    monkeypatch.setattr(settings, "reasoning_model", "optional-model")
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    reasoner = build_strategy_reasoner()

    assert reasoner.provider_name == "deterministic"
    assert reasoner.model_name == "rules-v1"


def test_deterministic_reasoner_bounds_long_theme_text() -> None:
    with SessionLocal() as db:
        pool = _complete_pool(db)
        proposal = DeterministicStrategyReasoner().propose(
            "deathtouch " * 300,
            pool,
            "Verdant Captain",
        )

        assert len(proposal.strategy_summary) <= 2_000
        assert all(len(package.purpose) <= 500 for package in proposal.packages)


def test_optimizer_assembles_exact_owned_legal_singleton_deck_and_keeps_package() -> None:
    with SessionLocal() as db:
        pool = _complete_pool(db)
        proposal = validate_reasoning_proposal(pool, _proposal())
        result = optimize_commander_deck(db, pool, proposal, "Verdant Captain")

        assert result["feasible"] is True
        assert result["validation"]["valid"] is True
        assert all(result["validation"]["checks"].values())
        assert sum(entry["quantity"] for entry in result["entries"]) == 100
        assert [entry["name"] for entry in result["entries"] if entry["is_commander"]] == [
            "Verdant Captain"
        ]
        forest = next(entry for entry in result["entries"] if entry["name"] == "Forest")
        assert forest["quantity"] == 37
        package = result["package_report"][0]
        assert package["minimum_satisfied"] is True
        assert len(package["included_cards"]) >= 3
        assert "Strategy Card 80" in {entry["name"] for entry in result["entries"]}


def test_optimizer_excludes_off_color_and_reports_insufficient_capacity() -> None:
    with SessionLocal() as db:
        pool = _complete_pool(db)
        pool.append(_add_candidate(
            db, index=950, name="Blue Intruder", type_line="Creature — Wizard",
            color_identity="U", retrieval_score=1_000,
        ))
        db.flush()
        result = optimize_commander_deck(db, pool, _proposal(), "Verdant Captain")
        assert result["feasible"] is True
        assert "Blue Intruder" not in {entry["name"] for entry in result["entries"]}

        tiny_pool = [pool[0], pool[-2]]  # commander plus Forest: only 81 owned cards
        failed = optimize_commander_deck(db, tiny_pool, _proposal(), "Verdant Captain")
        assert failed["feasible"] is False
        assert any(error["code"] == "deck_size" for error in failed["validation"]["errors"])


def test_model_commander_recommendation_is_advisory_not_a_constraint() -> None:
    with SessionLocal() as db:
        pool = _complete_pool(db)
        bad_recommendation = _proposal().model_copy(update={
            "recommended_commander": "Strategy Card 1"
        })
        result = optimize_commander_deck(db, pool, bad_recommendation)
        assert result["feasible"] is True
        assert result["commander"] == "Verdant Captain"


def test_hard_validator_detects_tampering_after_assembly() -> None:
    with SessionLocal() as db:
        pool = _complete_pool(db)
        result = optimize_commander_deck(db, pool, _proposal(), "Verdant Captain")
        entries = [dict(entry) for entry in result["entries"]]
        tampered = next(entry for entry in entries if entry["name"].startswith("Strategy Card"))
        tampered["quantity"] = 2
        report = validate_optimized_deck(db, pool, entries)
        codes = {error["code"] for error in report["errors"]}
        assert "singleton" in codes
        assert "availability" in codes
        assert "deck_size" in codes


def test_build_endpoint_uses_reasoner_for_packages_but_optimizer_for_deck(
    client, monkeypatch
) -> None:
    with SessionLocal() as db:
        _complete_pool(db)
        db.commit()

    from app.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr("app.main.build_strategy_reasoner", lambda: FakeReasoner())

    response = client.post("/api/deckbuilding/build", json={
        "theme": "Elf value strategy",
        "commander_name": "Verdant Captain",
    })
    assert response.status_code == 200
    payload = response.json()
    optimizer = payload["result"]["optimizer"]
    assert optimizer["feasible"] is True
    assert optimizer["validation"]["valid"] is True
    assert sum(entry["quantity"] for entry in optimizer["entries"]) == 100
    assert payload["result"]["reasoning_provenance"] == {
        "provider": "fixture",
        "model": "reasoner-v1",
        "schema_version": "1.0.0",
    }
    assert payload["result"]["decklist"] == optimizer["decklist"]
    run_id = payload["recommendation_run_id"]
    assert len(payload["candidate_options"]) == payload["pool_size"]

    draft_entries = [
        {
            key: entry[key]
            for key in ("scryfall_id", "oracle_id", "name", "quantity", "is_commander")
        }
        for entry in optimizer["entries"]
    ]
    validation = client.post(
        f"/api/deckbuilding/recommendations/{run_id}/validate",
        json={"entries": draft_entries},
    )
    assert validation.status_code == 200
    assert validation.json()["validation"]["valid"] is True

    saved = client.post(
        f"/api/deckbuilding/recommendations/{run_id}/save",
        json={"deck_name": "Generated Elf Draft", "entries": draft_entries},
    )
    assert saved.status_code == 200
    assert saved.json()["deck"]["name"] == "Generated Elf Draft"

    with SessionLocal() as db:
        assert db.get(RecommendationRun, run_id) is not None
        feedback = db.query(RecommendationFeedback).filter_by(run_id=run_id).one()
        assert feedback.outcome == "saved"
        commander_entry = next(entry for entry in draft_entries if entry["is_commander"])
        preference = db.get(RecommendationCardPreference, commander_entry["oracle_id"])
        assert preference.accepted_count == 1


def test_build_endpoint_works_without_anthropic_key(client, monkeypatch) -> None:
    with SessionLocal() as db:
        _complete_pool(db)
        db.commit()

    from app.config import settings
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "reasoning_provider", "deterministic")
    monkeypatch.setattr(settings, "reasoning_model", "rules-v1")

    response = client.post("/api/deckbuilding/build", json={
        "theme": "Elf value strategy",
        "commander_name": "Verdant Captain",
    })

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["result"]["reasoning_provenance"] == {
        "provider": "deterministic",
        "model": "rules-v1",
        "schema_version": "1.0.0",
    }
    assert payload["result"]["optimizer"]["validation"]["valid"] is True
    assert payload["recommendation_run_id"]
