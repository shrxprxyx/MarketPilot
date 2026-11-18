from fastapi.testclient import TestClient

from app.auth.rate_limit import clear_login_attempts
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
    """Using a refresh token twice must fail on the second use."""
    login = client.post("/api/v1/auth/login", json={
        "email": _EMAIL,
        "password": _PASSWORD,
    })
    rt = login.json()["refresh_token"]
    client.post("/api/v1/auth/refresh", json={"refresh_token": rt})  # rotate
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": rt})  # reuse
    assert r.status_code == 401


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