from __future__ import annotations

from app.config import settings
from app.enrichment.anthropic_provider import AnthropicEnrichmentProvider
from app.enrichment.base import EnrichmentProvider
from app.enrichment.openai_provider import OpenAIEnrichmentProvider


def provider_is_configured() -> bool:
    if settings.enrichment_provider == "openai":
        return settings.openai_requests_enabled and bool(settings.openai_api_key)
    if settings.enrichment_provider == "anthropic":
        return bool(settings.anthropic_api_key)
    return False


def build_enrichment_provider() -> EnrichmentProvider:
    if settings.enrichment_provider == "openai":
        if not settings.openai_requests_enabled:
            raise ValueError("OpenAI requests are disabled by OPENAI_REQUESTS_ENABLED")
        return OpenAIEnrichmentProvider(
            api_key=settings.openai_api_key,
            model=settings.enrichment_model,
            reasoning_effort=settings.enrichment_reasoning_effort,
            max_output_tokens_per_card=settings.enrichment_max_output_tokens_per_card,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
    if settings.enrichment_provider == "anthropic":
        return AnthropicEnrichmentProvider(
            api_key=settings.anthropic_api_key,
            model=settings.enrichment_model,
        )
    raise ValueError(f"Unsupported enrichment provider: {settings.enrichment_provider}")
