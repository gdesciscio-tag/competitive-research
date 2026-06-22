# compresearch/costs.py
from __future__ import annotations

# USD per 1,000,000 tokens: (input, output). Source: Claude API pricing.
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate the USD cost of a Claude call. None for an unknown model."""
    rates = PRICE_PER_MTOK.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    cost = (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
    return round(cost, 4)
