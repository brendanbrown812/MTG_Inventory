from app.config import settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.openai_provider import OpenAIEmbeddingProvider


def embedding_provider_is_configured() -> bool:
    return (
        settings.embedding_provider.casefold() == "openai"
        and bool(settings.openai_api_key)
        and settings.openai_requests_enabled
    )


def build_embedding_provider() -> EmbeddingProvider:
    provider = settings.embedding_provider.casefold()
    if provider != "openai":
        raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
    if not settings.openai_requests_enabled:
        raise ValueError("Paid OpenAI requests are disabled by OPENAI_REQUESTS_ENABLED")
    return OpenAIEmbeddingProvider(
        settings.openai_api_key,
        settings.embedding_model,
        settings.embedding_dimensions,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )
