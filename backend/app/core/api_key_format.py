"""Header-safe credential validation without echoing sensitive input."""

INVALID_API_KEY_MESSAGE = "API 키에 공백이나 지원하지 않는 문자가 있습니다. 키를 확인해 주세요."


def api_key_format_error(value: str, *, allow_empty: bool = False) -> str | None:
    if not value:
        return None if allow_empty else "API 키를 입력해 주세요."
    if any(not 33 <= ord(character) <= 126 for character in value):
        return INVALID_API_KEY_MESSAGE
    return None
