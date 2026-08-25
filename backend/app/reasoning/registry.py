from app.config import settings
from app.reasoning.anthropic_provider import AnthropicStrategyReasoner
from app.reasoning.base import StrategyReasoner
from app.reasoning.deterministic_provider import DeterministicStrategyReasoner
from app.reasoning.openai_provider import OpenAIStrategyReasoner
from app.logging_setup import get_logger


_log = get_logger(".reasoning")


class FallbackStrategyReasoner:
    """Use an optional provider when available, falling back to local rules."""

    def __init__(self, primary: StrategyReasoner, fallback: StrategyReasoner):
        self._primary = primary
        self._fallback = fallback
        self._active = primary

    @property
    def provider_name(self) -> str:
        return self._active.provider_name

    @property
    def model_name(self) -> str:
        return self._active.model_name

    def propose(self, theme: str, candidates: list[dict], commander_name: str | None):
        try:
            proposal = self._primary.propose(theme, candidates, commander_name)
            self._active = self._primary
            return proposal
        except Exception:
            _log.exception(
                "Optional reasoning provider failed provider=%s model=%s; using deterministic fallback",
                self._primary.provider_name,
                self._primary.model_name,
            )
            self._active = self._fallback
            return self._fallback.propose(theme, candidates, commander_name)


def build_strategy_reasoner() -> StrategyReasoner:
    deterministic = DeterministicStrategyReasoner()
    if settings.reasoning_provider == "deterministic":
        return deterministic
    if settings.reasoning_provider == "openai":
        if not settings.openai_requests_enabled:
            _log.info(
                "OpenAI reasoning is disabled by OPENAI_REQUESTS_ENABLED; "
                "using deterministic fallback"
            )
            return deterministic
        if not settings.openai_api_key:
            _log.warning(
                "OpenAI reasoning requested without OPENAI_API_KEY; using deterministic fallback"
            )
            return deterministic
        return FallbackStrategyReasoner(
            OpenAIStrategyReasoner(
                api_key=settings.openai_api_key,
                model=settings.reasoning_model,
                reasoning_effort=settings.reasoning_effort,
                max_output_tokens=settings.reasoning_max_output_tokens,
                timeout_seconds=settings.openai_timeout_seconds,
                max_retries=settings.openai_max_retries,
            ),
            deterministic,
        )
    if settings.reasoning_provider == "anthropic":
        if not settings.anthropic_api_key:
            _log.warning(
                "Anthropic reasoning requested without ANTHROPIC_API_KEY; using deterministic fallback"
            )
            return deterministic
        return FallbackStrategyReasoner(
            AnthropicStrategyReasoner(
                api_key=settings.anthropic_api_key,
                model=settings.reasoning_model,
            ),
            deterministic,
        )
    raise ValueError(f"Unsupported reasoning provider: {settings.reasoning_provider}")
