"""Agency settings and white-label branding (FR-TEN-07): any member reads, only admins write,
inputs are validated, and changes land in the audit log."""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db.engine as db_engine
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.main import app
from app.models.membership import Membership
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {
    "email": "tenant-admin@example.com",
    "password": "tenantadmin1",
    "tenant_name": "Tenant Co",
}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM tenants WHERE slug LIKE 'tenant-co%'"))
            await session.execute(text("DELETE FROM users WHERE email LIKE 'tenant-%@example.com'"))
            await session.commit()

    asyncio.run(_delete())
    yield
    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    r = client.post("/api/v1/auth/register", json=_ADMIN)
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _manager_token(admin_token: str) -> str:
    tenant_id = client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_id"]

    async def _seed() -> str:
        async with db_engine.AsyncSessionLocal() as session:
            user = User(
                email="tenant-manager@example.com", hashed_password=hash_password("irrelevant1234")
            )
            session.add(user)
            await session.flush()
            await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
            session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="manager"))
            await session.commit()
            return create_access_token(user.id, tenant_id, "manager")

    return asyncio.run(_seed())


def test_get_tenant_has_empty_branding_by_default(admin_token: str) -> None:
    r = client.get("/api/v1/tenant", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Tenant Co"
    assert body["plan"] == "free"
    assert body["branding"] == {"logo_url": None, "primary_color": None, "report_footer": None}


def test_admin_can_rename_and_set_branding(admin_token: str) -> None:
    r = client.patch(
        "/api/v1/tenant", json={"name": "  Tenant Co Renamed "}, headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Tenant Co Renamed"
    # the shell reads the name from /me, so it must follow
    assert client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_name"] == (
        "Tenant Co Renamed"
    )

    r = client.put(
        "/api/v1/tenant/branding",
        json={
            "logo_url": "https://cdn.example.com/logo.png",
            "primary_color": "#1F6F43",
            "report_footer": "Prepared by Tenant Co",
        },
        headers=_auth(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["branding"] == {
        "logo_url": "https://cdn.example.com/logo.png",
        "primary_color": "#1f6f43",
        "report_footer": "Prepared by Tenant Co",
    }

    # PUT replaces: omitted fields are cleared
    r = client.put(
        "/api/v1/tenant/branding", json={"primary_color": "#000000"}, headers=_auth(admin_token)
    )
    assert r.json()["branding"] == {
        "logo_url": None,
        "primary_color": "#000000",
        "report_footer": None,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"logo_url": "javascript:alert(1)"},
        {"logo_url": "data:image/png;base64,AAAA"},
        {"primary_color": "green"},
        {"primary_color": "#12345"},
        {"report_footer": "x" * 301},
    ],
)
def test_branding_rejects_bad_input(admin_token: str, payload: dict[str, str]) -> None:
    r = client.put("/api/v1/tenant/branding", json=payload, headers=_auth(admin_token))
    assert r.status_code == 422, r.text


def test_blank_name_rejected(admin_token: str) -> None:
    r = client.patch("/api/v1/tenant", json={"name": "   "}, headers=_auth(admin_token))
    assert r.status_code == 422


def test_manager_can_read_but_not_write(admin_token: str) -> None:
    token = _manager_token(admin_token)
    assert client.get("/api/v1/tenant", headers=_auth(token)).status_code == 200
    patch = client.patch("/api/v1/tenant", json={"name": "Nope"}, headers=_auth(token))
    assert patch.status_code == 403
    assert client.put("/api/v1/tenant/branding", json={}, headers=_auth(token)).status_code == 403


def test_requires_auth() -> None:
    assert client.get("/api/v1/tenant").status_code == 401


def test_changes_are_audited(admin_token: str) -> None:
    entries = client.get(
        "/api/v1/audit-log", params={"limit": 50}, headers=_auth(admin_token)
    ).json()["items"]
    actions = {e["action"] for e in entries}
    assert {"tenant.updated", "tenant.branding_updated"} <= actions
