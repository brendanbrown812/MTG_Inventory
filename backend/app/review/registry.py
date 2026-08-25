from __future__ import annotations

from app.config import settings
from app.logging_setup import get_logger
from app.review.base import DeckReviewProvider
from app.review.deterministic_provider import DeterministicDeckReviewer
from app.review.openai_provider import OpenAIDeckReviewer


_log = get_logger(".review")


class FallbackDeckReviewer:
    def __init__(self, primary: DeckReviewProvider, fallback: DeckReviewProvider):
        self._primary = primary
        self._fallback = fallback
        self._active = primary

    @property
    def provider_name(self) -> str:
        return self._active.provider_name

    @property
    def model_name(self) -> str:
        return self._active.model_name

    def suggest(self, current_list, candidates, theme_hint, existing_cards):
        try:
            result = self._primary.suggest(current_list, candidates, theme_hint, existing_cards)
            self._active = self._primary
            return result
        except Exception:
            _log.exception("Optional review provider failed in suggest mode; using local fallback")
            self._active = self._fallback
            return self._fallback.suggest(current_list, candidates, theme_hint, existing_cards)

    def audit(self, decklist, candidates, existing_cards):
        try:
            result = self._primary.audit(decklist, candidates, existing_cards)
            self._active = self._primary
            return result
        except Exception:
            _log.exception("Optional review provider failed in audit mode; using local fallback")
            self._active = self._fallback
            return self._fallback.audit(decklist, candidates, existing_cards)


def build_deck_reviewer() -> DeckReviewProvider:
    deterministic = DeterministicDeckReviewer(settings.review_fallback_model)
    provider = settings.review_provider.casefold()
    if provider == "deterministic":
        return deterministic
    if provider != "openai":
        raise ValueError(f"Unsupported review provider: {settings.review_provider}")
    if not settings.openai_requests_enabled:
        _log.info("OpenAI deck review is disabled by paid-request lock; using local fallback")
        return deterministic
    if not settings.openai_api_key:
        _log.warning("OpenAI deck review requested without an API key; using local fallback")
        return deterministic
    return FallbackDeckReviewer(
        OpenAIDeckReviewer(
            settings.openai_api_key,
            settings.review_model,
            reasoning_effort=settings.review_reasoning_effort,
            max_output_tokens=settings.review_max_output_tokens,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        ),
        deterministic,
    )
