import hashlib
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.auth.rate_limit import clear_login_attempts
from app.config import settings
from app.main import app

client = TestClient(app)

_EMAIL = "auto@example.com"
_PASSWORD = "password123"
_TENANT = "Auto Corp"


def test_register_rejects_short_password() -> None:
    r = client.post("/api/v1/auth/register", json={
        "email": "shortpw@example.com",
        "password": "abc123",  # under the 10-char minimum (FR-AUTH-03)
        "tenant_name": "Short PW Co",
    })
    assert r.status_code == 422


def test_register() -> None:
    r = client.post("/api/v1/auth/register", json={
        "email": _EMAIL,
        "password": _PASSWORD,
        "tenant_name": _TENANT,
    })
    assert r.status_code == 201
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data


def test_register_duplicate() -> None:
    r = client.post("/api/v1/auth/register", json={
        "email": _EMAIL,
        "password": _PASSWORD,
        "tenant_name": _TENANT,
    })
    assert r.status_code == 409


def test_login() -> None:
    r = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": _PASSWORD,
    })
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_wrong_password() -> None:
    r = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": "wrong",
    })
    assert r.status_code == 401


def test_refresh() -> None:
    login = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": _PASSWORD,
    })
    rt = login.json()["refresh_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_refresh_revoked_after_rotation() -> None:
    """Using a refresh token again after the grace window must fail."""
    login = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": _PASSWORD,
    })
    rt = login.json()["refresh_token"]
    client.post("/api/v1/auth/refresh", json={"refresh_token": rt})  # rotate
    _age_token(rt, 60)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": rt})  # reuse
    assert r.status_code == 401


def test_refresh_sent_twice_in_a_burst_keeps_the_session() -> None:
    """Two tabs (or a reload racing a request) can send the same cookie twice; not theft."""
    login = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": _PASSWORD,
    })
    rt1 = login.json()["refresh_token"]
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert first.status_code == 200
    assert second.status_code == 200
    # The session is still alive from the newest token.
    newest = second.json()["refresh_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": newest}).status_code == 200


def _age_token(raw: str, seconds: int) -> None:
    """Pretend `raw` was rotated `seconds` ago (the grace window is measured from that)."""
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    engine = create_engine(settings.database_url_direct)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE refresh_tokens SET updated_at = now() - make_interval(secs => :s) "
                "WHERE token_hash = :h"
            ),
            {"s": seconds, "h": token_hash},
        )
    engine.dispose()


def test_refresh_reuse_after_the_grace_window_revokes_the_whole_chain() -> None:
    """FR-AUTH-02: replaying a long-rotated token also kills the token it was rotated into."""
    login = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": _PASSWORD,
    })
    rt1 = login.json()["refresh_token"]
    rt2 = client.post("/api/v1/auth/refresh", json={"refresh_token": rt1}).json()["refresh_token"]
    _age_token(rt1, 60)
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": rt1})
    assert reuse.status_code == 401
    child = client.post("/api/v1/auth/refresh", json={"refresh_token": rt2})
    assert child.status_code == 401


def test_logout() -> None:
    login = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": _PASSWORD,
    })
    rt = login.json()["refresh_token"]
    r = client.post("/api/v1/auth/logout", json={"refresh_token": rt})
    assert r.status_code == 204


def test_refresh_after_logout() -> None:
    """Refresh token must be invalid after logout."""
    login = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": _PASSWORD,
    })
    rt = login.json()["refresh_token"]
    client.post("/api/v1/auth/logout", json={"refresh_token": rt})
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
    assert r.status_code == 401


async def test_login_locks_out_after_five_failures() -> None:
    """FR-AUTH-03: 5 failed attempts per minute per IP+email triggers a lockout."""
    email = "lockout@example.com"
    await clear_login_attempts(email, "testclient")  # isolate from other test runs

    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
        assert r.status_code == 401

    r = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert r.status_code == 429

    await clear_login_attempts(email, "testclient")

def _purge_registration_probes() -> None:
    """Remove the agencies and users the registration tests below create."""
    engine = create_engine(settings.database_url_direct)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE name LIKE 'RegTest %'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'regtest-%@example.com'"))
    engine.dispose()


@pytest.fixture
def clean_registrations() -> Iterator[None]:
    _purge_registration_probes()
    yield
    _purge_registration_probes()


def _register(email: str, tenant_name: str) -> httpx.Response:
    return client.post("/api/v1/auth/register", json={
        "email": email,
        "password": _PASSWORD,
        "tenant_name": tenant_name,
    })


def _slug_of(tenant_name: str) -> str:
    engine = create_engine(settings.database_url_direct)
    with engine.begin() as conn:
        slugs = conn.execute(
            text("SELECT slug FROM tenants WHERE name = :n ORDER BY created_at"),
            {"n": tenant_name},
        ).scalars().all()
    engine.dispose()
    return str(slugs[-1])


def test_two_agencies_can_share_a_name(clean_registrations: None) -> None:
    """Agency names are not unique; the second one gets a distinct slug, not a 500."""
    first = _register("regtest-one@example.com", "RegTest Same Name")
    second = _register("regtest-two@example.com", "RegTest same  name")
    third = _register("regtest-three@example.com", "RegTest Same Name")
    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 201
    assert _slug_of("RegTest Same Name") != "regtest-same-name"


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
def test_register_rejects_a_blank_or_oversized_agency_name(name: str) -> None:
    assert _register("regtest-bad@example.com", name).status_code == 422


def test_register_slug_is_url_safe(clean_registrations: None) -> None:
    assert _register("regtest-slug@example.com", "RegTest  Ünï & Co.!").status_code == 201
    assert _slug_of("RegTest  Ünï & Co.!") == "regtest-n-co"


def test_email_case_does_not_create_a_second_account(clean_registrations: None) -> None:
    assert _register("regtest-Case@Example.com", "RegTest Case One").status_code == 201
    again = _register("REGTEST-case@example.com", "RegTest Case Two")
    assert again.status_code == 409


def test_login_ignores_email_case(clean_registrations: None) -> None:
    assert _register("regtest-login@example.com", "RegTest Login").status_code == 201
    r = client.post("/api/v1/auth/login", json={
        "email": "RegTest-LOGIN@example.com",
        "password": _PASSWORD,
    })
    assert r.status_code == 200


def test_a_disabled_account_cannot_sign_in_or_keep_a_session(clean_registrations: None) -> None:
    email = "regtest-disabled@example.com"
    session = _register(email, "RegTest Disabled").json()
    engine = create_engine(settings.database_url_direct)
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false WHERE email = :e"), {"e": email})
    engine.dispose()

    login = client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert login.status_code == 403
    me = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {session['access_token']}"}
    )
    assert me.status_code == 401
    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert refresh.status_code == 401
