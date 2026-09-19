from pydantic import SecretStr

from app.core.config import Settings


def test_supabase_secret_key_alias_and_service_role_precedence(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "alias-secret")
    assert Settings(_env_file=None).supabase_service_role_key.get_secret_value() == "alias-secret"

    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "preferred-secret")
    assert (
        Settings(_env_file=None).supabase_service_role_key.get_secret_value() == "preferred-secret"
    )

    settings = Settings(_env_file=None, supabase_service_role_key=SecretStr("constructor-secret"))
    assert settings.supabase_service_role_key.get_secret_value() == "constructor-secret"
