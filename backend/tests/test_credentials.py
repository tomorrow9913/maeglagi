from app.core.credentials import decrypt_credential, encrypt_credential


def test_provider_credential_is_encrypted_at_rest() -> None:
    secret = "sk-test-provider-secret"

    encrypted = encrypt_credential(secret)

    assert encrypted != secret
    assert secret not in encrypted
    assert decrypt_credential(encrypted) == secret
