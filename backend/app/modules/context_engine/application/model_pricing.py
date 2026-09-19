"""Best-effort, short-lived prices for ordering provider-discovered models.

The model list always comes from the provider using the user's key. Prices are
reference data only; an unknown price never makes a model unavailable.
"""

import asyncio
import math
import time

import httpx

PRICE_MAP_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
_CACHE_SECONDS = 6 * 60 * 60
_prices: dict[tuple[str, str], float] = {}
_expires_at = 0.0
_lock = asyncio.Lock()


def _parse_prices(payload: dict[str, object]) -> dict[tuple[str, str], float]:
    prices: dict[tuple[str, str], float] = {}
    for model, details in payload.items():
        if not isinstance(details, dict):
            continue
        provider = details.get("litellm_provider")
        if provider not in {"openai", "anthropic", "nvidia_nim"}:
            continue
        input_cost = details.get("input_cost_per_token")
        output_cost = details.get("output_cost_per_token")
        if not isinstance(input_cost, (int, float)) or not isinstance(output_cost, (int, float)):
            continue
        cost = float(input_cost) + float(output_cost)
        if not math.isfinite(cost) or cost < 0:
            continue
        public_provider = "nvidia" if provider == "nvidia_nim" else provider
        prefix = f"{provider}/"
        model_id = model.removeprefix(prefix)
        # Some entries are routed through another vendor and have different rates.
        if "/" in model_id and public_provider != "nvidia":
            continue
        prices[(public_provider, model_id)] = cost
    return prices


async def model_prices() -> dict[tuple[str, str], float]:
    """Use cached prices on fetch failure; never send a user key to this source."""
    global _prices, _expires_at
    if time.monotonic() < _expires_at:
        return _prices
    async with _lock:
        if time.monotonic() < _expires_at:
            return _prices
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                response = await client.get(PRICE_MAP_URL)
                response.raise_for_status()
                payload = response.json()
                parsed = _parse_prices(payload) if isinstance(payload, dict) else {}
                if parsed:
                    _prices = parsed
                    _expires_at = time.monotonic() + _CACHE_SECONDS
                    return _prices
        except (httpx.HTTPError, ValueError, TypeError):
            pass
        _expires_at = time.monotonic() + 10 * 60
        return _prices
