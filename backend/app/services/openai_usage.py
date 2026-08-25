from __future__ import annotations

import math
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import OpenAIUsageRecord


PRICING_VERSION = "2026-08-24"


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float
    cache_write_multiplier: float = 1.25
    long_context_threshold: int | None = None
    long_input_multiplier: float = 1.0
    long_output_multiplier: float = 1.0


MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5.6-luna": ModelPrice(0.20, 0.02, 1.20, long_context_threshold=272_000,
                                long_input_multiplier=2.0, long_output_multiplier=1.5),
    "gpt-5.6-terra": ModelPrice(2.00, 0.20, 12.00, long_context_threshold=272_000,
                                 long_input_multiplier=2.0, long_output_multiplier=1.5),
    "gpt-5.6-sol": ModelPrice(4.00, 0.40, 20.00, long_context_threshold=272_000,
                               long_input_multiplier=2.0, long_output_multiplier=1.5),
    "text-embedding-3-small": ModelPrice(0.02, 0.02, 0.0, cache_write_multiplier=1.0),
}


class OpenAIBudgetError(RuntimeError):
    """Raised before a request when a local cost guard would be exceeded."""


_reservation_lock = threading.Lock()


def estimate_tokens(text: str) -> int:
    """Conservative no-network estimate for budget reservation purposes."""
    return max(1, math.ceil(len(text) / 3))


def calculate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    price = MODEL_PRICES.get(model)
    if price is None:
        raise OpenAIBudgetError(
            f"No reviewed price is configured for model {model!r}; request blocked"
        )
    input_tokens = max(0, int(input_tokens or 0))
    cached = min(input_tokens, max(0, int(cached_input_tokens or 0)))
    cache_write = min(input_tokens - cached, max(0, int(cache_write_tokens or 0)))
    regular = input_tokens - cached - cache_write
    input_multiplier = 1.0
    output_multiplier = 1.0
    if price.long_context_threshold and input_tokens > price.long_context_threshold:
        input_multiplier = price.long_input_multiplier
        output_multiplier = price.long_output_multiplier
    input_cost = (
        regular * price.input_per_million
        + cached * price.cached_input_per_million
        + cache_write * price.input_per_million * price.cache_write_multiplier
    ) * input_multiplier
    output_cost = max(0, int(output_tokens or 0)) * price.output_per_million * output_multiplier
    return round((input_cost + output_cost) / 1_000_000, 8)


def reserve_openai_usage(
    workflow: str,
    model: str,
    *,
    estimated_input_tokens: int,
    max_output_tokens: int = 0,
) -> str:
    estimated_cost = calculate_cost(
        model,
        input_tokens=estimated_input_tokens,
        output_tokens=max_output_tokens,
    )
    monthly_limit = float(settings.openai_monthly_budget_usd)
    request_limit = float(settings.openai_single_request_limit_usd)
    if request_limit <= 0 or estimated_cost > request_limit:
        raise OpenAIBudgetError(
            f"Estimated OpenAI request cost ${estimated_cost:.6f} exceeds the "
            f"local per-request limit of ${max(0, request_limit):.2f}"
        )
    if monthly_limit <= 0:
        raise OpenAIBudgetError("The local OpenAI monthly budget is disabled")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    reservation_id = str(uuid.uuid4())
    with _reservation_lock:
        with SessionLocal() as db:
            used = db.execute(
                select(
                    func.coalesce(func.sum(OpenAIUsageRecord.actual_cost_usd), 0.0)
                ).where(
                    OpenAIUsageRecord.created_at >= month_start,
                    OpenAIUsageRecord.status == "completed",
                )
            ).scalar_one()
            reserved = db.execute(
                select(
                    func.coalesce(func.sum(OpenAIUsageRecord.estimated_max_cost_usd), 0.0)
                ).where(
                    OpenAIUsageRecord.created_at >= month_start,
                    OpenAIUsageRecord.status == "reserved",
                )
            ).scalar_one()
            projected = float(used) + float(reserved) + estimated_cost
            if projected > monthly_limit:
                raise OpenAIBudgetError(
                    f"OpenAI request blocked: projected local monthly usage "
                    f"${projected:.6f} exceeds the ${monthly_limit:.2f} budget"
                )
            db.add(OpenAIUsageRecord(
                id=reservation_id,
                workflow=workflow,
                model=model,
                status="reserved",
                pricing_version=PRICING_VERSION,
                estimated_max_cost_usd=estimated_cost,
                created_at=now,
            ))
            db.commit()
    return reservation_id


def _usage_fields(response: Any) -> tuple[int, int, int, int]:
    usage = getattr(response, "usage", None)
    input_tokens = (
        getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_tokens", None)
        or getattr(usage, "total_tokens", None)
        or 0
    )
    output_tokens = getattr(usage, "output_tokens", None) or 0
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", None) or 0
    cache_write = getattr(details, "cache_write_tokens", None) or 0
    return int(input_tokens), int(cached), int(cache_write), int(output_tokens)


def complete_openai_usage(reservation_id: str, response: Any) -> None:
    input_tokens, cached, cache_write, output_tokens = _usage_fields(response)
    with SessionLocal() as db:
        record = db.get(OpenAIUsageRecord, reservation_id)
        if record is None:
            return
        record.input_tokens = input_tokens
        record.cached_input_tokens = cached
        record.cache_write_tokens = cache_write
        record.output_tokens = output_tokens
        record.actual_cost_usd = calculate_cost(
            record.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached,
            cache_write_tokens=cache_write,
        )
        record.response_id = getattr(response, "id", None)
        record.status = "completed"
        record.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()


def fail_openai_usage(reservation_id: str, error: BaseException) -> None:
    with SessionLocal() as db:
        record = db.get(OpenAIUsageRecord, reservation_id)
        if record is None:
            return
        record.status = "failed"
        record.error_type = type(error).__name__[:100]
        record.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()


def openai_usage_summary() -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        records = db.execute(
            select(OpenAIUsageRecord)
            .where(OpenAIUsageRecord.created_at >= month_start)
            .order_by(OpenAIUsageRecord.created_at.desc())
        ).scalars().all()
    spent = sum(float(row.actual_cost_usd or 0) for row in records if row.status == "completed")
    reserved = sum(row.estimated_max_cost_usd for row in records if row.status == "reserved")
    limit = max(0.0, float(settings.openai_monthly_budget_usd))
    return {
        "requests_enabled": settings.openai_requests_enabled,
        "month": month_start.strftime("%Y-%m"),
        "monthly_budget_usd": limit,
        "single_request_limit_usd": max(0.0, float(settings.openai_single_request_limit_usd)),
        "spent_usd": round(spent, 8),
        "reserved_usd": round(reserved, 8),
        "remaining_usd": round(max(0.0, limit - spent - reserved), 8),
        "pricing_version": PRICING_VERSION,
        "record_count": len(records),
        "recent": [
            {
                "id": row.id,
                "workflow": row.workflow,
                "model": row.model,
                "status": row.status,
                "estimated_max_cost_usd": row.estimated_max_cost_usd,
                "actual_cost_usd": row.actual_cost_usd,
                "input_tokens": row.input_tokens,
                "cached_input_tokens": row.cached_input_tokens,
                "cache_write_tokens": row.cache_write_tokens,
                "output_tokens": row.output_tokens,
                "created_at": row.created_at.isoformat() + "Z",
            }
            for row in records[:25]
        ],
        "notice": "Local estimate only; OpenAI project billing and budget settings remain authoritative.",
    }
