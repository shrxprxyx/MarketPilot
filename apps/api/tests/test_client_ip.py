"""The caller's address behind the web app's proxy (FR-AUTH-03 lockout, FR-TEN-06 audit ip)."""
import pytest
from starlette.requests import Request

from app.config import settings
from app.core.request import client_ip


def _request(forwarded: str | None, peer: str = "10.0.0.5") -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


@pytest.fixture
def trust(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trust_forwarded_for", True)


def test_header_is_ignored_unless_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trust_forwarded_for", False)
    assert client_ip(_request("203.0.113.9")) == "10.0.0.5"


def test_trusted_header_gives_the_browser_address(trust: None) -> None:
    assert client_ip(_request("203.0.113.9")) == "203.0.113.9"


def test_the_proxy_appended_entry_wins_over_a_spoofed_one(trust: None) -> None:
    assert client_ip(_request("198.51.100.1, 203.0.113.9")) == "203.0.113.9"


@pytest.mark.parametrize("value", [None, "", "not-an-ip"])
def test_missing_or_malformed_header_falls_back_to_the_connection(
    trust: None, value: str | None
) -> None:
    assert client_ip(_request(value)) == "10.0.0.5"
