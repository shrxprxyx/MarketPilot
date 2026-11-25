"""
Member management (FR-TEN-01).

Admins list members, change roles, and deactivate members; the last active admin
of a tenant can't be demoted, deactivated, or removed. Manager/member rows are
seeded directly via the DB (same shortcut tests/test_clients.py uses) rather than
through the invite flow (FR-AUTH-04, tests/test_invites.py) — these two features
are independent, and member management works whether a membership arrived via
invite or this shortcut.
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
    "email": "members-admin@example.com",
    "password": "membersadmin1",
    "tenant_name": "Members Co",
}
_TEST_EMAILS = (
    "members-admin@example.com",
    "members-manager@example.com",
    "members-member@example.com",
    "members-second-admin@example.com",
    "manager-no-access@example.com",
    "manager-target@example.com",
    "to-deactivate@example.com",
    "deactivated-login@example.com",
    "removable@example.com",
    "members-paged@example.com",
)


async def _add_membership(tenant_id: UUID, email: str, role: str) -> tuple[UUID, str]:
    """Returns (membership_id, access_token)."""
    async with db_engine.AsyncSessionLocal() as session:
        user = User(email=email, hashed_password=hash_password("irrelevant-1234"))
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        membership = Membership(user_id=user.id, tenant_id=tenant_id, role=role)
        session.add(membership)
        await session.flush()
        membership_id = membership.id
        user_id = user.id
        await session.commit()
    token = create_access_token(user_id, tenant_id, role)
    return membership_id, token


def _register(creds: dict) -> dict:
    client.post("/api/v1/auth/register", json=creds)  # may already exist
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM tenants WHERE slug = 'members-co'"))
            placeholders = ", ".join(f"'{e}'" for e in _TEST_EMAILS)
            await session.execute(text(f"DELETE FROM users WHERE email IN ({placeholders})"))
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _register(_ADMIN)["access_token"]


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    me = client.get("/api/v1/me", headers=_auth(admin_token)).json()
    return UUID(me["tenant_id"])


@pytest.fixture(scope="module")
def admin_membership_id(tenant_id: UUID, admin_token: str) -> UUID:
    members = client.get("/api/v1/members", headers=_auth(admin_token)).json()["items"]
    return UUID(next(m["id"] for m in members if m["role"] == "admin"))


def test_member_cannot_list_members(tenant_id: UUID) -> None:
    _, member_token = asyncio.run(
        _add_membership(tenant_id, "members-member@example.com", "member")
    )
    r = client.get("/api/v1/members", headers=_auth(member_token))
    assert r.status_code == 403


def test_admin_can_list_members(admin_token: str, tenant_id: UUID) -> None:
    r = client.get("/api/v1/members", headers=_auth(admin_token))
    assert r.status_code == 200
    emails = {m["email"] for m in r.json()["items"]}
    assert "members-admin@example.com" in emails


def test_member_list_is_paged_by_cursor(admin_token: str, tenant_id: UUID) -> None:
    asyncio.run(_add_membership(tenant_id, "members-paged@example.com", "member"))
    everything = client.get("/api/v1/members?limit=100", headers=_auth(admin_token)).json()
    assert everything["next_cursor"] is None and len(everything["items"]) >= 2

    walked: list[str] = []
    cursor = None
    while True:
        params = {"limit": 1} | ({"cursor": cursor} if cursor else {})
        page = client.get("/api/v1/members", params=params, headers=_auth(admin_token)).json()
        assert len(page["items"]) == 1
        walked.append(page["items"][0]["id"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert walked == [m["id"] for m in everything["items"]]

    bad = client.get("/api/v1/members?cursor=nonsense", headers=_auth(admin_token))
    assert bad.status_code == 400


def test_admin_can_promote_member_to_manager(admin_token: str, tenant_id: UUID) -> None:
    membership_id, _ = asyncio.run(
        _add_membership(tenant_id, "members-manager@example.com", "member")
    )
    r = client.patch(
        f"/api/v1/members/{membership_id}", json={"role": "manager"}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert r.json()["role"] == "manager"


def test_manager_cannot_patch_members(admin_token: str, tenant_id: UUID) -> None:
    membership_id, manager_token = asyncio.run(
        _add_membership(tenant_id, "manager-no-access@example.com", "manager")
    )
    other_membership_id, _ = asyncio.run(
        _add_membership(tenant_id, "manager-target@example.com", "member")
    )
    r = client.patch(
        f"/api/v1/members/{other_membership_id}",
        json={"role": "admin"},
        headers=_auth(manager_token),
    )
    assert r.status_code == 403


def test_deactivated_member_is_locked_out_immediately(admin_token: str, tenant_id: UUID) -> None:
    membership_id, member_token = asyncio.run(
        _add_membership(tenant_id, "to-deactivate@example.com", "member")
    )
    # Token is valid and works before deactivation.
    assert client.get("/api/v1/me", headers=_auth(member_token)).status_code == 200

    r = client.patch(
        f"/api/v1/members/{membership_id}",
        json={"status": "deactivated"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "deactivated"

    # Same still-unexpired access token must now be rejected — status is re-read
    # from the DB on every request, not trusted from the JWT.
    r = client.get("/api/v1/me", headers=_auth(member_token))
    assert r.status_code == 403


def test_deactivated_member_cannot_log_in(admin_token: str, tenant_id: UUID) -> None:
    async def _seed() -> tuple[str, str]:
        email = "deactivated-login@example.com"
        async with db_engine.AsyncSessionLocal() as session:
            user = User(email=email, hashed_password=hash_password("somepassword1"))
            session.add(user)
            await session.flush()
            await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
            membership = Membership(
                user_id=user.id, tenant_id=tenant_id, role="member", status="deactivated"
            )
            session.add(membership)
            await session.commit()
        return email, "somepassword1"

    email, password = asyncio.run(_seed())
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 403


def test_admin_can_remove_a_member(admin_token: str, tenant_id: UUID) -> None:
    membership_id, _ = asyncio.run(
        _add_membership(tenant_id, "removable@example.com", "member")
    )
    r = client.delete(f"/api/v1/members/{membership_id}", headers=_auth(admin_token))
    assert r.status_code == 204

    members = client.get("/api/v1/members", headers=_auth(admin_token)).json()["items"]
    assert not any(m["id"] == str(membership_id) for m in members)


def test_last_admin_cannot_be_demoted(admin_token: str, admin_membership_id: UUID) -> None:
    r = client.patch(
        f"/api/v1/members/{admin_membership_id}",
        json={"role": "manager"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409


def test_last_admin_cannot_be_deactivated(admin_token: str, admin_membership_id: UUID) -> None:
    r = client.patch(
        f"/api/v1/members/{admin_membership_id}",
        json={"status": "deactivated"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409


def test_last_admin_cannot_be_removed(admin_token: str, admin_membership_id: UUID) -> None:
    r = client.delete(f"/api/v1/members/{admin_membership_id}", headers=_auth(admin_token))
    assert r.status_code == 409


def test_second_admin_can_be_demoted_once_not_last(admin_token: str, tenant_id: UUID) -> None:
    second_admin_id, _ = asyncio.run(
        _add_membership(tenant_id, "members-second-admin@example.com", "admin")
    )
    # Now there are two active admins, so demoting one is allowed.
    r = client.patch(
        f"/api/v1/members/{second_admin_id}", json={"role": "manager"}, headers=_auth(admin_token)
    )
    assert r.status_code == 200
    assert r.json()["role"] == "manager"


def test_cross_tenant_member_not_found(admin_token: str) -> None:
    other = _register(
        {
            "email": "members-other-admin@example.com",
            "password": "othersadmin1",
            "tenant_name": "Other Members Co",
        }
    )
    other_me = client.get("/api/v1/me", headers=_auth(other["access_token"])).json()
    other_membership_id, _ = asyncio.run(
        _add_membership(UUID(other_me["tenant_id"]), "members-other-member@example.com", "member")
    )

    r = client.patch(
        f"/api/v1/members/{other_membership_id}",
        json={"role": "manager"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 404

    async def _cleanup_other() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM tenants WHERE slug = 'other-members-co'"))
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN "
                    "('members-other-admin@example.com', 'members-other-member@example.com')"
                )
            )
            await session.commit()

    asyncio.run(_cleanup_other())
