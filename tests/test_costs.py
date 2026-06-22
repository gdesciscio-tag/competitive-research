# tests/test_costs.py
from compresearch.costs import estimate_cost


def test_estimate_cost_opus():
    # opus 4.8: $5 / 1M input, $25 / 1M output
    # 1,000,000 input + 1,000,000 output = 5 + 25 = 30.0
    assert estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0


def test_estimate_cost_sonnet_partial():
    # sonnet 4.6: $3 / 1M input, $15 / 1M output
    # 200k input + 100k output = 0.6 + 1.5 = 2.1
    assert estimate_cost("claude-sonnet-4-6", 200_000, 100_000) == 2.1


def test_estimate_cost_unknown_model_is_none():
    assert estimate_cost("some-other-model", 1000, 1000) is None


def test_estimate_cost_zero_tokens():
    assert estimate_cost("claude-opus-4-8", 0, 0) == 0.0
