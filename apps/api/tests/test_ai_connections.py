"""
AI connections / BYOM credentials (FR-BYOM-01, FR-BYOM-02).

Admin and manager manage connections, members cannot (§2.2). Keys are
Fernet-encrypted at rest and never returned by the API.
"""
import asyncio
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.ai.providers as providers
import app.db.engine as db_engine
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.core.crypto import decrypt_secret, encrypt_secret
from app.db.rls import set_rls_context
from app.main import app
from app.models.membership import Membership
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {
    "email": "aiconn-admin@example.com",
    "password": "aiconnadmin1",
    "tenant_name": "AiConn Co",
}
_OTHER = {
    "email": "aiconn-other@example.com",
    "password": "aiconnother1",
    "tenant_name": "Other AiConn Co",
}
_SECRET = "sk-test-secret-abcd1234"


async def _add_membership(tenant_id: UUID, email: str, role: str) -> str:
    async with db_engine.AsyncSessionLocal() as session:
        user = User(email=email, hashed_password=hash_password("irrelevant-1234"))
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant_id, role=role))
        await session.commit()
        user_id = user.id
    return create_access_token(user_id, tenant_id, role)


def _register(creds: dict[str, str]) -> dict[str, Any]:
    client.post("/api/v1/auth/register", json=creds)
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE slug IN ('aiconn-co', 'other-aiconn-co')")
            )
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN ('aiconn-admin@example.com', "
                    "'aiconn-other@example.com', 'aiconn-manager@example.com', "
                    "'aiconn-member@example.com')"
                )
            )
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    return str(_register(_ADMIN)["access_token"])


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    return UUID(client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_id"])


@pytest.fixture(scope="module")
def manager_token(tenant_id: UUID) -> str:
    return asyncio.run(_add_membership(tenant_id, "aiconn-manager@example.com", "manager"))


@pytest.fixture(scope="module")
def member_token(tenant_id: UUID) -> str:
    return asyncio.run(_add_membership(tenant_id, "aiconn-member@example.com", "member"))


def _create(token: str, **overrides: Any) -> Any:
    body = {"provider": "openai", "label": "My OpenAI", "api_key": _SECRET} | overrides
    return client.post("/api/v1/ai/connections", json=body, headers=_auth(token))


def test_crypto_round_trip_and_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    import app.core.crypto as crypto

    token = encrypt_secret("hello")
    assert token != "hello"
    assert decrypt_secret(token) == "hello"

    # Rotation: a new first key still decrypts data written under the old key.
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        crypto.settings, "fernet_keys", f"{new_key},{crypto.settings.fernet_keys}"
    )
    assert decrypt_secret(token) == "hello"


def test_create_returns_last4_only(admin_token: str) -> None:
    r = _create(admin_token)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["key_last4"] == _SECRET[-4:]
    assert "api_key" not in data and "api_key_enc" not in data
    assert _SECRET not in r.text


def test_key_is_encrypted_at_rest(admin_token: str) -> None:
    conn_id = _create(admin_token, label="Encrypted").json()["id"]

    me = client.get("/api/v1/me", headers=_auth(admin_token)).json()

    async def _raw() -> str:
        async with db_engine.AsyncSessionLocal() as session:
            # RLS is forced, so scope the session to the owning tenant.
            await set_rls_context(session, tenant_id=me["tenant_id"])
            result = await session.execute(
                text("SELECT api_key_enc FROM ai_connections WHERE id = CAST(:i AS uuid)"),
                {"i": conn_id},
            )
            return str(result.scalar_one())

    stored = asyncio.run(_raw())
    assert _SECRET not in stored
    assert decrypt_secret(stored) == _SECRET


def test_list_never_exposes_key(admin_token: str) -> None:
    _create(admin_token, label="Listed")
    r = client.get("/api/v1/ai/connections", headers=_auth(admin_token))
    assert r.status_code == 200
    assert len(r.json()) >= 1
    assert _SECRET not in r.text


def test_manager_can_create_member_cannot(manager_token: str, member_token: str) -> None:
    assert _create(manager_token, label="By Manager").status_code == 201
    assert _create(member_token).status_code == 403
    assert client.get("/api/v1/ai/connections", headers=_auth(member_token)).status_code == 403


def test_validation_rules(admin_token: str) -> None:
    assert _create(admin_token, api_key=None).status_code == 422  # openai needs a key
    assert _create(admin_token, provider="ollama", api_key=None).status_code == 422  # needs URL
    assert (
        _create(admin_token, provider="ollama", api_key=None, base_url="ftp://x").status_code == 422
    )
    ok = _create(admin_token, provider="ollama", api_key=None, base_url="http://localhost:11434")
    assert ok.status_code == 201
    assert ok.json()["key_last4"] is None


def test_test_endpoint_lists_models_and_passes_decrypted_key(
    admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
        seen["url"], seen["headers"] = url, headers
        return {"data": [{"id": "gpt-b"}, {"id": "gpt-a"}]}

    monkeypatch.setattr(providers, "_get_json", fake_get_json)
    conn_id = _create(admin_token, label="Testable").json()["id"]
    r = client.post(f"/api/v1/ai/connections/{conn_id}/test", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "models": ["gpt-a", "gpt-b"]}
    assert seen["headers"]["Authorization"] == f"Bearer {_SECRET}"
    assert seen["url"].endswith("/models")


def test_test_endpoint_reports_rejected_credentials(
    admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
        raise providers.ProviderError("The provider rejected the credentials.")

    monkeypatch.setattr(providers, "_get_json", fake_get_json)
    conn_id = _create(admin_token, label="Bad Key").json()["id"]
    r = client.post(f"/api/v1/ai/connections/{conn_id}/test", headers=_auth(admin_token))
    assert r.status_code == 400
    assert _SECRET not in r.text


def test_delete_connection(admin_token: str) -> None:
    conn_id = _create(admin_token, label="Doomed").json()["id"]
    assert (
        client.delete(f"/api/v1/ai/connections/{conn_id}", headers=_auth(admin_token)).status_code
        == 204
    )
    r = client.post(f"/api/v1/ai/connections/{conn_id}/test", headers=_auth(admin_token))
    assert r.status_code == 404


def test_cross_tenant_access_returns_404(admin_token: str) -> None:
    other = str(_register(_OTHER)["access_token"])
    conn_id = _create(other, label="Other Tenant").json()["id"]
    r = client.delete(f"/api/v1/ai/connections/{conn_id}", headers=_auth(admin_token))
    assert r.status_code == 404
    listing = client.get("/api/v1/ai/connections", headers=_auth(admin_token)).json()
    assert all(c["id"] != conn_id for c in listing)


def test_creation_is_audit_logged(admin_token: str) -> None:
    _create(admin_token, label="Audited")
    r = client.get("/api/v1/audit-log", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    assert "ai_connection.created" in r.text
    assert _SECRET not in r.text
