from __future__ import annotations


MODEL_PRICES: dict[str, dict[str, dict[str, float]]] = {
    "anthropic": {
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
        "claude-opus-4-7": {"input": 15.00, "output": 75.00},
    },
}

SEED_INPUT_TOKENS_PER_CARD = 650
SEED_OUTPUT_TOKENS_PER_CARD = 220


def get_model_prices(provider: str, model: str) -> dict[str, float] | None:
    return MODEL_PRICES.get(provider, {}).get(model)


def estimate_cost(
    provider: str,
    model: str,
    cards: int,
    avg_input: float | None,
    avg_output: float | None,
) -> float:
    prices = get_model_prices(provider, model)
    if not prices:
        return 0.0
    input_per_card = avg_input if avg_input is not None else SEED_INPUT_TOKENS_PER_CARD
    output_per_card = avg_output if avg_output is not None else SEED_OUTPUT_TOKENS_PER_CARD
    return cards * (
        input_per_card * prices["input"] / 1_000_000
        + output_per_card * prices["output"] / 1_000_000
    )
