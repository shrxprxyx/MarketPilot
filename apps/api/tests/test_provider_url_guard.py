"""
SSRF guard for tenant-supplied provider base URLs (FR-BYOM-01). The guard runs before every
provider request, so these tests hit the real _get_json against a real local HTTP server.
"""
import asyncio
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

import app.ai.providers as providers
from app.ai.providers import ProviderError, _check_destination
from app.config import settings


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"models": [{"name": "llama3"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def local_server() -> Iterator[int]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def _check(url: str, *, allow_private: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "allow_private_base_urls", allow_private)
    asyncio.run(_check_destination(url))


ALWAYS_BLOCKED = [
    "http://169.254.169.254/latest/meta-data",  # cloud metadata
    "http://169.254.0.1:8080",
    "http://[fe80::1]/",
    "http://[::ffff:169.254.169.254]/",  # IPv4-mapped IPv6 form of the metadata address
    "http://0.0.0.0:11434",
    "http://224.0.0.1/",
    "http://240.0.0.1/",  # reserved range
]
PRIVATE = [
    "http://127.0.0.1:11434",
    "http://localhost:11434",
    "http://[::1]:11434",
    "http://10.0.0.5",
    "http://192.168.1.20:8080",
    "http://172.16.0.9",
]


@pytest.mark.parametrize("url", ALWAYS_BLOCKED)
@pytest.mark.parametrize("allow_private", [False, True])
def test_link_local_and_non_routable_are_always_blocked(
    url: str, allow_private: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ProviderError, match="not allowed"):
        _check(url, allow_private=allow_private, monkeypatch=monkeypatch)


@pytest.mark.parametrize("url", PRIVATE)
def test_private_and_loopback_blocked_by_default(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ProviderError, match="Private and loopback"):
        _check(url, allow_private=False, monkeypatch=monkeypatch)


@pytest.mark.parametrize("url", PRIVATE)
def test_private_and_loopback_allowed_when_opted_in(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _check(url, allow_private=True, monkeypatch=monkeypatch)  # does not raise


def test_public_address_and_bad_schemes(monkeypatch: pytest.MonkeyPatch) -> None:
    _check("https://8.8.8.8/v1", allow_private=False, monkeypatch=monkeypatch)  # public: fine
    for bad in ("ftp://example.com", "file:///etc/passwd", "http://", "not a url"):
        with pytest.raises(ProviderError):
            _check(bad, allow_private=True, monkeypatch=monkeypatch)


def test_unresolvable_host_is_a_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProviderError, match="resolve"):
        _check("http://does-not-exist.invalid", allow_private=True, monkeypatch=monkeypatch)


def test_requests_hit_the_guard_before_any_network_call(
    local_server: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"http://127.0.0.1:{local_server}/api/tags"
    monkeypatch.setattr(settings, "allow_private_base_urls", False)
    with pytest.raises(ProviderError, match="Private and loopback"):
        asyncio.run(providers._get_json(url, {}))
    monkeypatch.setattr(settings, "allow_private_base_urls", True)
    assert asyncio.run(providers._get_json(url, {})) == {"models": [{"name": "llama3"}]}


def test_metadata_address_is_blocked_even_when_private_urls_are_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "allow_private_base_urls", True)
    with pytest.raises(ProviderError, match="not allowed"):
        asyncio.run(providers._get_json("http://169.254.169.254/latest/meta-data", {}))
