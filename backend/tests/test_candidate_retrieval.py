from __future__ import annotations

import json
from pathlib import Path

from app.database import SessionLocal
from app.mechanics.profile import MechanicProfile
from app.models import (
    CardPrinting, InventoryLine, MechanicProfileRecord, OracleCard,
    RecommendationCardPreference,
)
from app.services.candidate_retrieval import RETRIEVAL_VERSION, retrieve_owned_candidates


_SUITE = json.loads(
    (Path(__file__).parents[1] / "evals" / "mtg_mechanics_v1.json").read_text(encoding="utf-8")
)


def _golden(key: str) -> MechanicProfile:
    return MechanicProfile.model_validate(_SUITE["profiles"][key])


def _add_owned(
    db,
    profile: MechanicProfile,
    *,
    legal: bool = True,
    color_identity: str = "[]",
    quantity: int = 1,
    second_printing_quantity: int = 0,
) -> None:
    oracle_text = "\n".join(hook.evidence for hook in profile.hooks) or "No rules text."
    db.add(OracleCard(
        oracle_id=profile.oracle_id,
        name=profile.card_name,
        type_line="Artifact" if profile.card_name == "Sol Ring" else "Creature",
        oracle_text=oracle_text,
        color_identity=color_identity,
        legalities_json=json.dumps({"commander": "legal" if legal else "not_legal"}),
        keywords="[]",
    ))
    first_id = f"printing-{profile.oracle_id}-a"
    db.add(CardPrinting(scryfall_id=first_id, oracle_id=profile.oracle_id))
    db.add(InventoryLine(scryfall_id=first_id, quantity=quantity))
    if second_printing_quantity:
        second_id = f"printing-{profile.oracle_id}-b"
        db.add(CardPrinting(scryfall_id=second_id, oracle_id=profile.oracle_id))
        db.add(InventoryLine(scryfall_id=second_id, quantity=second_printing_quantity))
    db.add(MechanicProfileRecord(
        oracle_id=profile.oracle_id,
        schema_version=profile.schema_version,
        taxonomy_version=profile.taxonomy_version,
        profile_json=profile.model_dump_json(),
        provider="fixture",
        model="golden",
        confidence=profile.confidence,
        is_current=True,
    ))


def _aristocrat_profile() -> MechanicProfile:
    return MechanicProfile.model_validate({
        "oracle_id": "oracle-blood-artist",
        "card_name": "Blood Artist",
        "roles": ["sacrifice_payoff"],
        "hooks": [{
            "verb": "rewards",
            "mechanic": "creature_death",
            "scope": "all_creatures",
            "condition": "creature_dies",
            "evidence": "Whenever Blood Artist or another creature dies",
        }],
        "universal_utility": {"tier": "none", "reasons": []},
        "confidence": 0.98,
    })


def test_semantic_concepts_replace_literal_substring_matching() -> None:
    with SessionLocal() as db:
        _add_owned(db, _aristocrat_profile())
        _add_owned(db, _golden("sol_ring"))
        db.commit()

        first = retrieve_owned_candidates(db, "an aristocrats strategy")
        second = retrieve_owned_candidates(db, "an aristocrats strategy")

        assert [item["name"] for item in first] == [item["name"] for item in second]
        artist = next(item for item in first if item["name"] == "Blood Artist")
        assert "aristocrats" not in artist["oracle_text"].casefold()
        assert artist["retrieval"]["components"]["role"] > 0
        assert artist["retrieval"]["components"]["semantic"] > 0
        assert any("Role match" in reason for reason in artist["retrieval"]["reasons"])


def test_structured_relationships_reward_indirect_synergy_and_penalize_conflicts() -> None:
    with SessionLocal() as db:
        for key in ("fynn", "bow_of_nylea", "muldrotha", "rest_in_peace"):
            _add_owned(db, _golden(key))
        db.commit()

        fynn_pool = retrieve_owned_candidates(
            db, "", seed_names={"Fynn, the Fangbearer"},
            exclude_names={"Fynn, the Fangbearer"},
        )
        bow = next(item for item in fynn_pool if item["name"] == "Bow of Nylea")
        assert bow["retrieval"]["components"]["mechanic_relationship"] >= 16
        assert any("supplies mechanics" in reason for reason in bow["retrieval"]["reasons"])

        graveyard_pool = retrieve_owned_candidates(
            db, "graveyard recursion", seed_names={"Muldrotha, the Gravetide"},
            exclude_names={"Muldrotha, the Gravetide"},
        )
        rest = next(item for item in graveyard_pool if item["name"] == "Rest in Peace")
        assert rest["retrieval"]["components"]["anti_synergy_penalty"] == -24
        assert any("prevents mechanics" in reason for reason in rest["retrieval"]["reasons"])


def test_known_combo_is_a_separate_transparent_score_component() -> None:
    with SessionLocal() as db:
        _add_owned(db, _golden("chatterfang"))
        _add_owned(db, _golden("pitiless_plunderer"), quantity=1, second_printing_quantity=2)
        db.commit()

        pool = retrieve_owned_candidates(
            db, "", seed_names={"Chatterfang, Squirrel General"},
            exclude_names={"Chatterfang, Squirrel General"},
        )
        plunderer = next(item for item in pool if item["name"] == "Pitiless Plunderer")
        assert plunderer["owned_quantity"] == 3
        assert plunderer["retrieval"]["components"]["known_combo"] == 30
        assert any("Known conditional combo" in reason for reason in plunderer["retrieval"]["reasons"])


def test_collection_legality_and_commander_color_identity_filter_before_scoring() -> None:
    commander = _golden("fynn")
    legal_green = _golden("bow_of_nylea")
    illegal = _golden("sol_ring").model_copy(update={"oracle_id": "illegal-id", "card_name": "Illegal Ring"})
    off_color = _golden("muldrotha")
    with SessionLocal() as db:
        _add_owned(db, commander, color_identity='["G"]')
        _add_owned(db, legal_green, color_identity='["G"]')
        _add_owned(db, illegal, legal=False)
        _add_owned(db, off_color, color_identity='["B","G","U"]')
        db.commit()

        pool = retrieve_owned_candidates(
            db, "deathtouch", commander_name="Fynn, the Fangbearer"
        )
        names = {item["name"] for item in pool}
        assert "Bow of Nylea" in names
        assert "Illegal Ring" not in names
        assert "Muldrotha, the Gravetide" not in names

        pinned = retrieve_owned_candidates(
            db,
            "graveyard recursion",
            commander_name="Fynn, the Fangbearer",
            limit=1,
        )
        assert [item["name"] for item in pinned] == ["Fynn, the Fangbearer"]


def test_candidate_endpoint_returns_score_components_without_ai(client) -> None:
    with SessionLocal() as db:
        _add_owned(db, _golden("sol_ring"))
        db.commit()

    response = client.post("/api/deckbuilding/candidates", json={"query": "extra mana"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval"]["version"] == RETRIEVAL_VERSION
    candidate = payload["retrieval"]["candidates"][0]
    assert candidate["name"] == "Sol Ring"
    assert set(candidate["components"]) == {
        "role", "mechanic_relationship", "semantic", "known_combo",
        "universal_utility", "functional_role", "basic_land_floor",
        "user_feedback", "anti_synergy_penalty",
    }
    assert candidate["total_score"] == round(sum(candidate["components"].values()), 4)


def test_explicit_feedback_becomes_a_transparent_future_score() -> None:
    with SessionLocal() as db:
        profile = _golden("sol_ring")
        _add_owned(db, profile)
        db.flush()
        db.add(RecommendationCardPreference(
            oracle_id=profile.oracle_id, accepted_count=3, rejected_count=1
        ))
        db.commit()

        card = retrieve_owned_candidates(db, "mana", limit=1)[0]
        assert card["retrieval"]["components"]["user_feedback"] == 4.0
        assert any("3 accepted, 1 rejected" in reason for reason in card["retrieval"]["reasons"])
