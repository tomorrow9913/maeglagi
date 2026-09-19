import pytest

from app.modules.context_engine.application.model_pricing import _parse_prices
from app.modules.context_engine.application.model_roles import ModelRole, options_by_role


class Adapter:
    id = "openai"
    capabilities = ("chat", "embedding", "structuredOutput", "transcription", "models")


def test_prices_only_use_matching_direct_provider_and_token_rates() -> None:
    prices = _parse_prices(
        {
            "gpt-new": {
                "litellm_provider": "openai",
                "input_cost_per_token": 0.000002,
                "output_cost_per_token": 0.000008,
            },
            "azure/gpt-new": {
                "litellm_provider": "azure",
                "input_cost_per_token": 0.000001,
                "output_cost_per_token": 0.000001,
            },
            "gpt-unknown": {"litellm_provider": "openai"},
        }
    )

    assert set(prices) == {("openai", "gpt-new")}
    assert prices[("openai", "gpt-new")] == pytest.approx(0.00001)


def test_live_models_are_ordered_by_known_price_then_unknown_price() -> None:
    options = options_by_role(
        [(Adapter(), ["gpt-expensive-mini", "gpt-unknown", "gpt-cheap"])],
        {("openai", "gpt-expensive-mini"): 8.0, ("openai", "gpt-cheap"): 1.0},
    )

    assert [item.model for item in options[ModelRole.ANSWER]] == [
        "gpt-cheap",
        "gpt-expensive-mini",
        "gpt-unknown",
    ]
