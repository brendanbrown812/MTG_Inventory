from app.config import settings
from app.reasoning.anthropic_provider import AnthropicStrategyReasoner
from app.reasoning.base import StrategyReasoner


def build_strategy_reasoner() -> StrategyReasoner:
    if settings.reasoning_provider == "anthropic":
        return AnthropicStrategyReasoner(
            api_key=settings.anthropic_api_key,
            model=settings.reasoning_model,
        )
    raise ValueError(f"Unsupported reasoning provider: {settings.reasoning_provider}")
