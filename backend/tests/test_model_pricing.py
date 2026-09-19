from datetime import date

import pytest

from app.modules.context_engine.application.model_pricing import _parse_prices
from app.modules.context_engine.application.model_roles import ModelRole, options_by_role
from app.modules.context_engine.application.provider import ModelInfo


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
        [
            (
                Adapter(),
                [
                    ModelInfo(id=model)
                    for model in ("gpt-expensive-mini", "gpt-unknown", "gpt-cheap")
                ],
            )
        ],
        {("openai", "gpt-expensive-mini"): 8.0, ("openai", "gpt-cheap"): 1.0},
    )

    assert [item.model for item in options[ModelRole.ANSWER]] == [
        "gpt-cheap",
        "gpt-expensive-mini",
        "gpt-unknown",
    ]


def test_offered_default_leads_with_price_order_for_other_live_models() -> None:
    options = options_by_role(
        [
            (
                Adapter(),
                [
                    ModelInfo(id="gpt-default"),
                    ModelInfo(id="gpt-cheap"),
                    ModelInfo(id="gpt-retired", shutdown_date=date(2020, 1, 1)),
                ],
            )
        ],
        {("openai", "gpt-default"): 8.0, ("openai", "gpt-cheap"): 1.0},
        defaults={"openai": {"answer": "gpt-default"}},
    )

    assert [item.model for item in options[ModelRole.ANSWER]] == ["gpt-default", "gpt-cheap"]
