"""Validated, DNS-pinned outbound connections to a workspace Ollama server.

``allowed_private_hosts`` is administrator policy, never a value from a workspace
endpoint.  Callers must await the factory and close the returned async client.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlsplit

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_MAX_URL_BYTES = 2048
_DNS_TIMEOUT_SECONDS = 10.0
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)
_BLOCKED_IPV6_TRANSITIONS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16")
)
_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud
        ipaddress.ip_address("168.63.129.16"),  # Azure platform endpoint
        ipaddress.ip_address("192.0.0.192"),  # Oracle Cloud
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IPv6 IMDS
        ipaddress.ip_address("fd20:ce::254"),  # Google Cloud IPv6 metadata
    }
)


def _canonical_host(host: str) -> str:
    if not host or "%" in host or host.endswith("."):
        raise ValueError("Invalid Ollama hostname")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return str(address)
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("Invalid Ollama hostname") from exc
    if len(ascii_host) > 253 or any(
        not _HOST_LABEL.fullmatch(label) for label in ascii_host.split(".")
    ):
        raise ValueError("Invalid Ollama hostname")
    return ascii_host


def normalize_ollama_url(value: str) -> str:
    """Canonicalize a server URL; DNS and network policy are checked by the factory."""
    if not isinstance(value, str) or len(value) > _MAX_URL_BYTES:
        raise ValueError("Invalid Ollama URL")
    try:
        url_bytes = len(value.encode("utf-8"))
    except UnicodeError:
        raise ValueError("Invalid Ollama URL") from None
    if (
        not value
        or url_bytes > _MAX_URL_BYTES
        or value != value.strip()
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
        or "\\" in value
        or "?" in value
        or "#" in value
    ):
        raise ValueError("Invalid Ollama URL")
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("Ollama URL must use HTTP or HTTPS")
        if "@" in parts.netloc or "%" in parts.netloc:
            raise ValueError("Ollama URL must not contain credentials or encoded authority")
        host = _canonical_host(parts.hostname or "")
        port = parts.port
    except ValueError as exc:
        raise ValueError("Invalid Ollama URL") from exc
    if port == 0 or parts.netloc.endswith(":"):
        raise ValueError("Invalid Ollama port")
    path = parts.path
    if path and (
        not path.startswith("/")
        or "%" in path
        or "//" in path
        or any(segment in {".", ".."} for segment in path.split("/"))
    ):
        raise ValueError("Invalid Ollama URL path")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    return f"{parts.scheme}://{authority}{path.rstrip('/')}"


def _allowed_host(host: str, port: int, entries: list[str] | tuple[str, ...]) -> bool:
    for entry in entries:
        if not isinstance(entry, str):
            raise ValueError("Invalid administrator Ollama allowlist")
        try:
            parsed = urlsplit(normalize_ollama_url(f"https://{entry}"))
        except ValueError as exc:
            raise ValueError("Invalid administrator Ollama allowlist") from exc
        if parsed.path or parsed.hostname != host:
            if parsed.path:
                raise ValueError("Invalid administrator Ollama allowlist")
            continue
        if parsed.port is None or parsed.port == port:
            return True
    return False


def _safe_address(value: str, *, allow_private: bool) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.scope_id is not None:
        return False
    if isinstance(address, ipaddress.IPv6Address) and any(
        address in network for network in _BLOCKED_IPV6_TRANSITIONS
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address in _METADATA_ADDRESSES
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or (address.is_reserved and not address.is_loopback)
    ):
        return False
    if address.is_global:
        return True
    return allow_private and (
        address.is_loopback or any(address in network for network in _PRIVATE_NETWORKS)
    )


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global


async def _resolve_addresses(host: str, port: int) -> list[str]:
    try:
        records = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=_DNS_TIMEOUT_SECONDS,
        )
    except (OSError, UnicodeError, TimeoutError):
        raise ValueError("Ollama hostname could not be resolved") from None
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses:
        raise ValueError("Ollama hostname has no addresses")
    return addresses


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, host: str, port: int, address: str) -> None:
        self.host = host
        self.port = port
        self.address = address
        self._delegate = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        if host != self.host or port != self.port:
            raise httpcore.ConnectError("Ollama destination changed")
        return await self._delegate.connect_tcp(
            self.address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, path: str, **kwargs) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are not allowed for Ollama")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, scheme: str, host: str, port: int, address: str) -> None:
        super().__init__(trust_env=False)
        # HTTPX 0.28 delegates to httpcore here.  Replacing its pool keeps
        # HTTPX's normal streaming and exception translation while injecting
        # a backend that never resolves the hostname again.
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=_PinnedNetworkBackend(host, port, address)
        )
        self._origin = (scheme, host, port)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        origin = (
            request.url.scheme,
            request.url.host,
            request.url.port or (443 if request.url.scheme == "https" else 80),
        )
        if origin != self._origin:
            raise httpx.ConnectError("Ollama destination changed", request=request)
        return await super().handle_async_request(request)


async def make_ollama_client(
    base_url: str,
    api_key: str = "",
    *,
    allow_private_network: bool = False,
    allowed_private_hosts: list[str] | tuple[str, ...] = (),
    timeout: float = 10.0,
) -> httpx.AsyncClient:
    """Return a client connected only to a validated, pinned Ollama address.

    The URL remains the configured hostname so HTTP Host and TLS SNI/certificate
    verification use that name.  Every DNS answer is checked before selecting
    the first address, and httpcore receives only that numeric address.
    """
    url = normalize_ollama_url(base_url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if not isinstance(allow_private_network, bool) or not isinstance(
        allowed_private_hosts, (list, tuple)
    ):
        raise ValueError("Invalid administrator Ollama policy")
    allow_private = allow_private_network or _allowed_host(host, port, allowed_private_hosts)
    addresses = await _resolve_addresses(host, port)
    if not all(_safe_address(address, allow_private=allow_private) for address in addresses):
        raise ValueError("Ollama address is not permitted")
    if parts.scheme == "http" and (
        not allow_private or any(_is_public_address(address) for address in addresses)
    ):
        raise ValueError("Public Ollama endpoints require HTTPS")
    if not isinstance(api_key, str) or any(not 33 <= ord(char) <= 126 for char in api_key):
        raise ValueError("Invalid Ollama API key")
    if api_key and parts.scheme == "http" and not allow_private_network:
        raise ValueError("Ollama API keys require HTTPS outside self-hosted private networks")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return httpx.AsyncClient(
        base_url=url,
        headers=headers,
        transport=_PinnedTransport(parts.scheme, host, port, addresses[0]),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    )
