from __future__ import annotations

from app.config import settings
from app.enrichment.anthropic_provider import AnthropicEnrichmentProvider
from app.enrichment.base import EnrichmentProvider


def provider_is_configured() -> bool:
    if settings.enrichment_provider == "anthropic":
        return bool(settings.anthropic_api_key)
    return False


def build_enrichment_provider() -> EnrichmentProvider:
    if settings.enrichment_provider == "anthropic":
        return AnthropicEnrichmentProvider(
            api_key=settings.anthropic_api_key,
            model=settings.enrichment_model,
        )
    raise ValueError(f"Unsupported enrichment provider: {settings.enrichment_provider}")
