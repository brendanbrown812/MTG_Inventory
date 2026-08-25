from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import OpenAIUsageRecord
from app.services.openai_usage import (
    OpenAIBudgetError,
    calculate_cost,
    complete_openai_usage,
    fail_openai_usage,
    openai_usage_summary,
    reserve_openai_usage,
)


def _response(*, input_tokens=1_000, output_tokens=100, cached=200, cache_write=100):
    return SimpleNamespace(
        id="resp_test",
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_tokens_details=SimpleNamespace(
                cached_tokens=cached,
                cache_write_tokens=cache_write,
            ),
        ),
    )


def test_reservation_reconciles_actual_cached_and_cache_write_usage(monkeypatch):
    monkeypatch.setattr(settings, "openai_monthly_budget_usd", 1.0)
    monkeypatch.setattr(settings, "openai_single_request_limit_usd", 0.10)
    reservation_id = reserve_openai_usage(
        "reasoning", "gpt-5.6-luna", estimated_input_tokens=2_000, max_output_tokens=500
    )
    complete_openai_usage(reservation_id, _response())

    with SessionLocal() as db:
        record = db.get(OpenAIUsageRecord, reservation_id)
        assert record is not None
        assert record.status == "completed"
        assert record.response_id == "resp_test"
        assert record.cached_input_tokens == 200
        assert record.cache_write_tokens == 100
        assert record.actual_cost_usd == pytest.approx(0.000289)

    summary = openai_usage_summary()
    assert summary["spent_usd"] == pytest.approx(0.000289)
    assert summary["reserved_usd"] == 0
    assert "api" not in str(summary).lower() or "key" not in str(summary).lower()


def test_single_request_limit_blocks_before_creating_record(monkeypatch):
    monkeypatch.setattr(settings, "openai_single_request_limit_usd", 0.001)
    with pytest.raises(OpenAIBudgetError, match="per-request limit"):
        reserve_openai_usage(
            "reasoning", "gpt-5.6-luna", estimated_input_tokens=10_000,
            max_output_tokens=10_000,
        )
    with SessionLocal() as db:
        assert db.scalar(select(OpenAIUsageRecord).limit(1)) is None


def test_monthly_limit_counts_active_reservations(monkeypatch):
    monkeypatch.setattr(settings, "openai_monthly_budget_usd", 0.0003)
    monkeypatch.setattr(settings, "openai_single_request_limit_usd", 1.0)
    reserve_openai_usage(
        "semantic_embedding", "text-embedding-3-small", estimated_input_tokens=10_000
    )
    with pytest.raises(OpenAIBudgetError, match="monthly usage"):
        reserve_openai_usage(
            "semantic_embedding", "text-embedding-3-small", estimated_input_tokens=10_000
        )


def test_failed_request_releases_reservation(monkeypatch):
    monkeypatch.setattr(settings, "openai_monthly_budget_usd", 0.00021)
    monkeypatch.setattr(settings, "openai_single_request_limit_usd", 1.0)
    first = reserve_openai_usage(
        "semantic_embedding", "text-embedding-3-small", estimated_input_tokens=10_000
    )
    fail_openai_usage(first, TimeoutError("not persisted"))
    second = reserve_openai_usage(
        "semantic_embedding", "text-embedding-3-small", estimated_input_tokens=10_000
    )
    assert second != first
    with SessionLocal() as db:
        failed = db.get(OpenAIUsageRecord, first)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error_type == "TimeoutError"


def test_unknown_model_is_blocked_and_embedding_price_is_known():
    with pytest.raises(OpenAIBudgetError, match="No reviewed price"):
        calculate_cost("unreviewed-model", input_tokens=1)
    assert calculate_cost("text-embedding-3-small", input_tokens=1_000_000) == 0.02


def test_usage_endpoint_exposes_controls_but_not_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "secret-must-not-leak")
    response = client.get("/api/openai/usage")
    assert response.status_code == 200
    body = response.json()
    assert body["monthly_budget_usd"] == settings.openai_monthly_budget_usd
    assert "secret-must-not-leak" not in response.text
    assert "api_key" not in response.text
