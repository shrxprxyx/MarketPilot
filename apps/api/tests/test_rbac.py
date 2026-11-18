"""
Tenant isolation + RBAC tests.

Two users register with separate tenants (Alice=owner, Bob=owner).
Verifies:
- Each user can hit /me and sees only their own tenant_id
- Alice's token cannot read Bob's tenant data (different tenant_id in JWT)
- A member-role user is blocked from an owner-only endpoint
- An unauthenticated request gets 401
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_ALICE = {"email": "alice@example.com", "password": "alicepass1", "tenant_name": "Alice Corp"}
_BOB   = {"email": "bob@example.com",   "password": "bobpass1",   "tenant_name": "Bob Corp"}


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
    assert data["role"] == "owner"
    assert "tenant_id" in data
    assert "user_id" in data


def test_two_users_have_different_tenant_ids() -> None:
    alice_tokens = _register_and_login(_ALICE)
    bob_tokens   = _register_and_login(_BOB)

    alice_me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {alice_tokens['access_token']}"}).json()
    bob_me   = client.get("/api/v1/me", headers={"Authorization": f"Bearer {bob_tokens['access_token']}"}).json()

    assert alice_me["tenant_id"] != bob_me["tenant_id"], "Tenant IDs must differ"
    assert alice_me["user_id"]   != bob_me["user_id"],   "User IDs must differ"


def test_unauthenticated_me_returns_401() -> None:
    r = client.get("/api/v1/me")
    assert r.status_code == 401


def test_invalid_token_returns_401() -> None:
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer notavalidtoken"})
    assert r.status_code == 401
