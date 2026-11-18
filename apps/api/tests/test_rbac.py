"""
JWT claims + auth dependency tests.

Two users register with separate tenants (Alice=admin, Bob=admin). Verifies:
- Each user can hit /me and sees only their own tenant_id
- Two independently registered tenants get distinct tenant_id and user_id
- An unauthenticated request gets 401
- An invalid token gets 401

Real cross-tenant DB-level isolation (RLS) is covered separately in
tests/isolation/test_tenant_isolation.py, not here.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_ALICE = {"email": "alice@example.com", "password": "alicepass1!", "tenant_name": "Alice Corp"}
_BOB = {"email": "bob@example.com", "password": "bobpassword1", "tenant_name": "Bob Corp"}


def _register_and_login(creds: dict) -> dict:
    client.post("/api/v1/auth/register", json=creds)  # may already exist
    r = client.post("/api/v1/auth/login", json={
        "email": creds["email"], "password": creds["password"]
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_me_returns_own_tenant() -> None:
    tokens = _register_and_login(_ALICE)
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "admin"
    assert "tenant_id" in data
    assert "user_id" in data


def test_two_users_have_different_tenant_ids() -> None:
    alice_tokens = _register_and_login(_ALICE)
    bob_tokens = _register_and_login(_BOB)

    headers_a = {"Authorization": f"Bearer {alice_tokens['access_token']}"}
    headers_b = {"Authorization": f"Bearer {bob_tokens['access_token']}"}
    alice_me = client.get("/api/v1/me", headers=headers_a).json()
    bob_me = client.get("/api/v1/me", headers=headers_b).json()

    assert alice_me["tenant_id"] != bob_me["tenant_id"], "Tenant IDs must differ"
    assert alice_me["user_id"] != bob_me["user_id"], "User IDs must differ"


def test_unauthenticated_me_returns_401() -> None:
    r = client.get("/api/v1/me")
    assert r.status_code == 401


def test_invalid_token_returns_401() -> None:
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer notavalidtoken"})
    assert r.status_code == 401
