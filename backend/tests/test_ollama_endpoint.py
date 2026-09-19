"""Ollama URL policy and pinned transport, without external network access."""

from __future__ import annotations

import asyncio
import socket
import ssl

import httpx
import pytest

from app.core import ollama_endpoint as endpoint


@pytest.mark.parametrize(
    "url",
    [
        "http://user:password@ollama.example",
        "https://ollama.example?token=secret",
        "https://ollama.example#fragment",
        "https://ollama.example/%2e%2e/api",
        "https://ollama.example/a%2fb",
        "https://ollama.example/a\\b",
        "https://ollama.example/a/../b",
        "https://ollama.example//admin",
        "https://ollama.example:0",
        "https://ollama.example:65536",
        "https://ollama.example:",
        "https://*.example.com",
        "file:///etc/passwd",
        " https://ollama.example",
    ],
)
def test_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError):
        endpoint.normalize_ollama_url(url)


def test_normalizes_valid_names_paths_and_ipv6() -> None:
    assert endpoint.normalize_ollama_url("https://OLLAMA.Example/prefix/") == (
        "https://ollama.example/prefix"
    )
    assert endpoint.normalize_ollama_url("http://[FC00::1]:11434/") == "http://[fc00::1]:11434"


def test_url_byte_limit_applies_before_parsing() -> None:
    prefix = "https://models.example/"
    at_limit = prefix + "a" * (2048 - len(prefix))
    assert endpoint.normalize_ollama_url(at_limit) == at_limit
    with pytest.raises(ValueError, match="Invalid Ollama URL"):
        endpoint.normalize_ollama_url(at_limit + "a")
    with pytest.raises(ValueError, match="Invalid Ollama URL"):
        endpoint.normalize_ollama_url(prefix + "é" * 1015)


@pytest.mark.parametrize(
    ("url", "answers", "policy", "accepted"),
    [
        ("https://models.example", ["8.8.8.8"], {}, True),
        ("http://models.example", ["8.8.8.8"], {}, False),
        ("https://models.example", ["8.8.8.8", "10.0.0.2"], {}, False),
        ("https://models.example", ["2001:4860:4860::8888"], {}, True),
        ("https://models.example", ["::ffff:8.8.8.8"], {}, True),
        ("https://models.example", ["::ffff:127.0.0.1"], {}, False),
        ("http://ollama", ["172.18.0.3"], {}, False),
        ("http://ollama", ["172.18.0.3"], {"allow_private_network": True}, True),
        ("http://localhost:11434", ["127.0.0.1"], {"allow_private_network": True}, True),
        ("http://[::1]:11434", ["::1"], {"allow_private_network": True}, True),
        ("http://[fd12::5]:11434", ["fd12::5"], {"allow_private_network": True}, True),
        (
            "http://ollama:11434",
            ["172.18.0.3"],
            {"allowed_private_hosts": ("ollama:11434",)},
            True,
        ),
        (
            "http://ollama:11435",
            ["172.18.0.3"],
            {"allowed_private_hosts": ("ollama:11434",)},
            False,
        ),
        (
            "http://ollama.evil:11434",
            ["172.18.0.3"],
            {"allowed_private_hosts": ("ollama:11434",)},
            False,
        ),
        ("https://models.example", ["169.254.169.254"], {"allow_private_network": True}, False),
        ("https://models.example", ["100.100.100.200"], {"allow_private_network": True}, False),
        ("https://models.example", ["192.0.0.192"], {"allow_private_network": True}, False),
        ("https://models.example", ["fd00:ec2::254"], {"allow_private_network": True}, False),
        ("https://models.example", ["fd20:ce::254"], {"allow_private_network": True}, False),
        ("https://models.example", ["fe80::1"], {"allow_private_network": True}, False),
        ("https://models.example", ["224.0.0.1"], {"allow_private_network": True}, False),
        ("https://models.example", ["0.0.0.0"], {"allow_private_network": True}, False),
        ("https://models.example", ["240.0.0.1"], {"allow_private_network": True}, False),
        ("https://models.example", ["198.18.0.1"], {"allow_private_network": True}, False),
        ("https://models.example", ["192.0.0.1"], {"allow_private_network": True}, False),
        ("https://models.example", ["64:ff9b::a9fe:a9fe"], {}, False),
        ("https://models.example", ["64:ff9b::808:808"], {}, False),
        ("https://models.example", ["64:ff9b:1::a9fe:a9fe"], {}, False),
        ("https://models.example", ["2002:a9fe:a9fe::1"], {}, False),
        ("https://models.example", ["2001:0:4136:e378::1"], {}, False),
        (
            "https://models.example",
            ["64:ff9b::a9fe:a9fe"],
            {"allow_private_network": True},
            False,
        ),
        (
            "https://models.example",
            ["8.8.8.8", "169.254.169.254"],
            {"allowed_private_hosts": ("models.example",)},
            False,
        ),
        (
            "http://models.example",
            ["8.8.8.8", "10.0.0.2"],
            {"allow_private_network": True},
            False,
        ),
    ],
)
async def test_address_policy(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    answers: list[str],
    policy: dict,
    accepted: bool,
) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return answers

    monkeypatch.setattr(endpoint, "_resolve_addresses", resolve)
    if accepted:
        client = await endpoint.make_ollama_client(url, **policy)
        await client.aclose()
    else:
        with pytest.raises(ValueError):
            await endpoint.make_ollama_client(url, **policy)


async def test_dns_resolver_preserves_every_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()

    async def getaddrinfo(host: str, port: int, **kwargs):
        assert host == "models.example"
        assert port == 443
        assert kwargs == {"type": socket.SOCK_STREAM}
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", getaddrinfo)
    assert await endpoint._resolve_addresses("models.example", 443) == ["8.8.8.8", "::1"]


async def test_dns_resolution_times_out_with_redacted_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(endpoint, "_DNS_TIMEOUT_SECONDS", 0.01)

    async def getaddrinfo(_host: str, _port: int, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(loop, "getaddrinfo", getaddrinfo)
    with pytest.raises(ValueError, match="^Ollama hostname could not be resolved$") as exc:
        await endpoint._resolve_addresses("private-secret.example", 443)
    assert "private-secret" not in str(exc.value)
    assert exc.value.__cause__ is None


class _ResponseStream:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.writes: list[bytes] = []
        self.tls_host: str | None = None
        self.tls_verified = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        result, self.response = self.response, b""
        return result

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.writes.append(buffer)

    async def aclose(self) -> None:
        pass

    async def start_tls(
        self, ssl_context: ssl.SSLContext, server_hostname: str | None = None, timeout=None
    ):
        self.tls_host = server_hostname
        self.tls_verified = ssl_context.verify_mode == ssl.CERT_REQUIRED
        return self

    def get_extra_info(self, info: str):
        return None


async def test_pin_preserves_tls_name_host_and_bearer_without_rebinding(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    calls: list[tuple[str, int]] = []
    stream = _ResponseStream(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    async def resolve(_host: str, _port: int) -> list[str]:
        calls.append((_host, _port))
        return ["8.8.8.8"] if len(calls) == 1 else ["127.0.0.1"]

    async def connect(_self, host: str, port: int, **_kwargs):
        calls.append((host, port))
        return stream

    monkeypatch.setattr(endpoint, "_resolve_addresses", resolve)
    monkeypatch.setattr(endpoint.AutoBackend, "connect_tcp", connect)
    async with await endpoint.make_ollama_client(
        "https://Models.Example/prefix", "private-key"
    ) as client:
        response = await client.get("/api/tags")
        assert response.text == "ok"
        assert client.follow_redirects is False
        assert client._trust_env is False

    assert calls == [("models.example", 443), ("8.8.8.8", 443)]
    assert stream.tls_host == "models.example"
    assert stream.tls_verified
    request_bytes = b"".join(stream.writes)
    assert b"host: models.example\r\n" in request_bytes.lower()
    assert b"authorization: bearer private-key\r\n" in request_bytes.lower()
    assert b"GET /prefix/api/tags HTTP/1.1" in request_bytes
    assert "private-key" not in caplog.text


async def test_redirect_and_foreign_origin_are_not_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _ResponseStream(
        b"HTTP/1.1 302 Found\r\nLocation: https://evil.example/api/tags\r\n"
        b"Content-Length: 0\r\n\r\n"
    )
    connections: list[str] = []

    async def resolve(_host: str, _port: int) -> list[str]:
        return ["8.8.8.8"]

    async def connect(_self, host: str, port: int, **_kwargs):
        connections.append(host)
        return stream

    monkeypatch.setattr(endpoint, "_resolve_addresses", resolve)
    monkeypatch.setattr(endpoint.AutoBackend, "connect_tcp", connect)
    async with await endpoint.make_ollama_client("https://models.example", "private-key") as client:
        response = await client.get("/api/tags")
        assert response.status_code == 302
        with pytest.raises(httpx.ConnectError):
            await client.get("https://evil.example/api/tags")
    assert connections == ["8.8.8.8"]
    assert b"private-key" not in repr(response).encode()


async def test_key_never_appears_in_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return ["169.254.169.254"]

    monkeypatch.setattr(endpoint, "_resolve_addresses", resolve)
    with pytest.raises(ValueError) as exc:
        await endpoint.make_ollama_client("https://models.example", "private-key")
    assert "private-key" not in str(exc.value)

    async def private_resolve(_host: str, _port: int) -> list[str]:
        return ["172.18.0.3"]

    monkeypatch.setattr(endpoint, "_resolve_addresses", private_resolve)
    with pytest.raises(ValueError):
        await endpoint.make_ollama_client(
            "http://ollama:11434", "private-key", allowed_private_hosts=("ollama",)
        )
    client = await endpoint.make_ollama_client(
        "http://ollama:11434", "private-key", allow_private_network=True
    )
    assert client.headers["Authorization"] == "Bearer private-key"
    await client.aclose()
