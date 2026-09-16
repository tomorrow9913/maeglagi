import httpx


async def validate_provider_credential(provider: str, api_key: str) -> tuple[bool, str]:
    if provider == "openai":
        url = "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"}
    elif provider == "anthropic":
        url = "https://api.anthropic.com/v1/models?limit=1"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    else:
        return False, "지원하지 않는 provider입니다."

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError:
        return False, "Provider에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."

    if response.is_success:
        return True, "사용할 수 있는 API key입니다."
    if response.status_code in {401, 403}:
        return False, "유효하지 않거나 권한이 없는 API key입니다."
    return False, f"Provider가 API key를 확인하지 못했습니다 ({response.status_code})."
