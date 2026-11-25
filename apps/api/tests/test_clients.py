"""
Clients + brand profiles (FR-TEN-02, FR-TEN-03).

RBAC per the §2.2 capability matrix: admin/manager can create/edit/archive
clients and brand profiles; member can only read them. Since there's no invite
endpoint yet (FR-AUTH-04), a "manager"/"member" in the same tenant is created by
inserting the membership row directly and minting a token for it — exactly the
same shortcut tests/isolation/ uses, not a new pattern.
"""
import asyncio
from uuid import UUID

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
    "email": "clients-admin@example.com",
    "password": "clientsadmin1",
    "tenant_name": "Clients Co",
}
_OTHER_ADMIN = {
    "email": "clients-other@example.com",
    "password": "clientsother1",
    "tenant_name": "Other Clients Co",
}


async def _add_membership(tenant_id: UUID, email: str, role: str) -> str:
    """Creates a user + membership in an existing tenant and returns an access
    token for them, bypassing the (not-yet-built) invite flow."""
    async with db_engine.AsyncSessionLocal() as session:
        user = User(email=email, hashed_password=hash_password("irrelevant-1234"))
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        membership = Membership(user_id=user.id, tenant_id=tenant_id, role=role)
        session.add(membership)
        await session.commit()
        user_id = user.id
    return create_access_token(user_id, tenant_id, role)


def _register(creds: dict) -> dict:
    client.post("/api/v1/auth/register", json=creds)  # may already exist
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "DELETE FROM tenants WHERE slug IN ('clients-co', 'other-clients-co')"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN "
                    "('clients-admin@example.com', 'clients-other@example.com', "
                    "'clients-manager@example.com', 'clients-member@example.com')"
                )
            )
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _register(_ADMIN)["access_token"]


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {admin_token}"}).json()
    return UUID(me["tenant_id"])


@pytest.fixture(scope="module")
def manager_token(tenant_id: UUID) -> str:
    return asyncio.run(
        _add_membership(tenant_id, "clients-manager@example.com", "manager")
    )


@pytest.fixture(scope="module")
def member_token(tenant_id: UUID) -> str:
    return asyncio.run(
        _add_membership(tenant_id, "clients-member@example.com", "member")
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_member_cannot_create_client(member_token: str) -> None:
    r = client.post(
        "/api/v1/clients", json={"name": "Blocked Co"}, headers=_auth(member_token)
    )
    assert r.status_code == 403


def test_admin_can_create_client(admin_token: str) -> None:
    r = client.post(
        "/api/v1/clients",
        json={"name": "Acme", "website_url": "https://acme.test", "industry": "retail"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "Acme"
    assert data["status"] == "active"


def test_manager_can_create_client(manager_token: str) -> None:
    r = client.post(
        "/api/v1/clients", json={"name": "Manager Made Co"}, headers=_auth(manager_token)
    )
    assert r.status_code == 201


def test_member_can_list_and_read_clients(admin_token: str, member_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "Readable Co"}, headers=_auth(admin_token)
    ).json()

    listing = client.get("/api/v1/clients", headers=_auth(member_token)).json()
    assert any(c["id"] == created["id"] for c in listing["items"])

    detail = client.get(f"/api/v1/clients/{created['id']}", headers=_auth(member_token))
    assert detail.status_code == 200


def test_update_client(admin_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "Editable Co"}, headers=_auth(admin_token)
    ).json()

    r = client.patch(
        f"/api/v1/clients/{created['id']}",
        json={"industry": "finance"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["industry"] == "finance"
    assert r.json()["name"] == "Editable Co"  # untouched fields stay as-is


def test_member_cannot_update_client(admin_token: str, member_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "Not Editable Co"}, headers=_auth(admin_token)
    ).json()

    r = client.patch(
        f"/api/v1/clients/{created['id']}",
        json={"industry": "finance"},
        headers=_auth(member_token),
    )
    assert r.status_code == 403


def test_archive_client_is_a_soft_delete(admin_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "Archivable Co"}, headers=_auth(admin_token)
    ).json()

    r = client.delete(f"/api/v1/clients/{created['id']}", headers=_auth(admin_token))
    assert r.status_code == 204

    detail = client.get(f"/api/v1/clients/{created['id']}", headers=_auth(admin_token))
    assert detail.status_code == 200
    assert detail.json()["status"] == "archived"


def test_client_not_found_returns_404(admin_token: str) -> None:
    r = client.get(
        "/api/v1/clients/00000000-0000-0000-0000-000000000000", headers=_auth(admin_token)
    )
    assert r.status_code == 404


def test_cross_tenant_client_read_returns_404_not_leaked(admin_token: str) -> None:
    other_tokens = _register(_OTHER_ADMIN)
    other_client = client.post(
        "/api/v1/clients",
        json={"name": "Other Tenant Co"},
        headers=_auth(other_tokens["access_token"]),
    ).json()

    r = client.get(f"/api/v1/clients/{other_client['id']}", headers=_auth(admin_token))
    assert r.status_code == 404


def test_pagination_limit_and_cursor(admin_token: str) -> None:
    for i in range(3):
        client.post(
            "/api/v1/clients", json={"name": f"Page Co {i}"}, headers=_auth(admin_token)
        )

    first_page = client.get(
        "/api/v1/clients", params={"limit": 2}, headers=_auth(admin_token)
    ).json()
    assert len(first_page["items"]) == 2
    assert first_page["next_cursor"] is not None

    second_page = client.get(
        "/api/v1/clients",
        params={"limit": 2, "cursor": first_page["next_cursor"]},
        headers=_auth(admin_token),
    ).json()
    first_ids = {c["id"] for c in first_page["items"]}
    second_ids = {c["id"] for c in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_brand_profile_not_found_before_upsert(admin_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "No Brand Co"}, headers=_auth(admin_token)
    ).json()
    r = client.get(f"/api/v1/clients/{created['id']}/brand-profile", headers=_auth(admin_token))
    assert r.status_code == 404


def test_brand_profile_upsert_and_read(admin_token: str, member_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "Branded Co"}, headers=_auth(admin_token)
    ).json()

    body = {"voice": "friendly", "tone": "casual", "keywords": ["fast", "local"]}
    r = client.put(
        f"/api/v1/clients/{created['id']}/brand-profile", json=body, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert r.json()["voice"] == "friendly"

    read = client.get(
        f"/api/v1/clients/{created['id']}/brand-profile", headers=_auth(member_token)
    )
    assert read.status_code == 200
    assert read.json()["keywords"] == ["fast", "local"]


def test_member_cannot_write_brand_profile(admin_token: str, member_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "Protected Brand Co"}, headers=_auth(admin_token)
    ).json()
    r = client.put(
        f"/api/v1/clients/{created['id']}/brand-profile",
        json={"voice": "nope"},
        headers=_auth(member_token),
    )
    assert r.status_code == 403


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://acme.test", "acme.test"])
def test_website_must_be_an_http_address(admin_token: str, url: str) -> None:
    r = client.post(
        "/api/v1/clients",
        json={"name": "Bad Url Co", "website_url": url},
        headers=_auth(admin_token),
    )
    assert r.status_code == 422


def _create_with_goals(admin_token: str, goals: list[str]) -> int:
    r = client.post(
        "/api/v1/clients",
        json={"name": "Goals Limit Co", "goals": goals},
        headers=_auth(admin_token),
    )
    return r.status_code


def test_goals_are_limited_in_number_and_length(admin_token: str) -> None:
    assert _create_with_goals(admin_token, ["g"] * 21) == 422
    assert _create_with_goals(admin_token, ["g" * 301]) == 422
    assert _create_with_goals(admin_token, ["  "]) == 422


def test_editing_a_client_applies_the_same_limits(admin_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "Edit Limits Co"}, headers=_auth(admin_token)
    ).json()
    url = f"/api/v1/clients/{created['id']}"
    bad = client.patch(url, json={"website_url": "javascript:alert(1)"}, headers=_auth(admin_token))
    ok = client.patch(
        url,
        json={"website_url": " https://ok.test ", "goals": [" grow "]},
        headers=_auth(admin_token),
    )
    assert bad.status_code == 422
    assert ok.status_code == 200, ok.text
    assert ok.json()["website_url"] == "https://ok.test"
    assert ok.json()["goals"] == ["grow"]
