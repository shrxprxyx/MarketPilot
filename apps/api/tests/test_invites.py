"""
Invite flow (FR-AUTH-04).

Admins invite by email + role; the raw token is only ever returned once, at
creation (standing in for "shown in the UI for copying" since there's no email
provider). Covers both accept-invite cases: a brand-new email (sets a password)
and an email that already has an account elsewhere (must authenticate with its
existing password instead of setting a new one).
"""
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
    "email": "invites-admin@example.com",
    "password": "invitesadmin1",
    "tenant_name": "Invites Co",
}
_TEST_EMAILS = (
    "invites-admin@example.com",
    "invites-other-admin@example.com",
    "invites-member-blocked@example.com",
    "new-invitee@example.com",
    "brand-new@example.com",
    "revoke-me@example.com",
)


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
            await session.execute(
                text("DELETE FROM tenants WHERE slug IN ('invites-co', 'other-invites-co')")
            )
            placeholders = ", ".join(f"'{e}'" for e in _TEST_EMAILS)
            await session.execute(text(f"DELETE FROM users WHERE email IN ({placeholders})"))
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _register(_ADMIN)["access_token"]


def test_member_cannot_create_invite(admin_token: str) -> None:
    # Seed a member via the admin's own tenant to prove non-admins are blocked.
    r = client.get("/api/v1/me", headers=_auth(admin_token))
    tenant_id = r.json()["tenant_id"]

    async def _seed_member() -> str:
        async with db_engine.AsyncSessionLocal() as session:
            user = User(
                email="invites-member-blocked@example.com",
                hashed_password=hash_password("irrelevant-1234"),
            )
            session.add(user)
            await session.flush()
            await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
            membership = Membership(user_id=user.id, tenant_id=tenant_id, role="member")
            session.add(membership)
            await session.commit()
            uid = user.id
        return create_access_token(uid, tenant_id, "member")

    member_token = asyncio.run(_seed_member())
    r = client.post(
        "/api/v1/members/invite",
        json={"email": "nope@example.com", "role": "member"},
        headers=_auth(member_token),
    )
    assert r.status_code == 403


def test_admin_can_create_invite_and_it_is_listed(admin_token: str) -> None:
    r = client.post(
        "/api/v1/members/invite",
        json={"email": "new-invitee@example.com", "role": "manager"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["email"] == "new-invitee@example.com"
    assert data["role"] == "manager"
    assert "invite_token" in data and len(data["invite_token"]) > 20

    pending = client.get("/api/v1/members/invites", headers=_auth(admin_token)).json()
    assert any(i["email"] == "new-invitee@example.com" for i in pending)


def test_accept_invite_creates_new_user_and_membership(admin_token: str) -> None:
    invite = client.post(
        "/api/v1/members/invite",
        json={"email": "brand-new@example.com", "role": "member"},
        headers=_auth(admin_token),
    ).json()

    r = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite["invite_token"], "password": "newpassword1"},
    )
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert "access_token" in tokens

    me = client.get("/api/v1/me", headers=_auth(tokens["access_token"])).json()
    assert me["role"] == "member"

    # Token is one-time use.
    r2 = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite["invite_token"], "password": "newpassword1"},
    )
    assert r2.status_code == 401


def test_accept_invite_for_existing_user_requires_their_real_password(
    admin_token: str,
) -> None:
    existing_email = "invites-other-admin@example.com"
    _register(
        {"email": existing_email, "password": "othersadmin1", "tenant_name": "Other Invites Co"}
    )

    invite = client.post(
        "/api/v1/members/invite",
        json={"email": existing_email, "role": "manager"},
        headers=_auth(admin_token),
    ).json()

    wrong = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite["invite_token"], "password": "wrongpassword1"},
    )
    assert wrong.status_code == 401

    right = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite["invite_token"], "password": "othersadmin1"},
    )
    assert right.status_code == 200, right.text

    # That user is now a member of BOTH tenants.
    me = client.get(
        "/api/v1/me", headers=_auth(right.json()["access_token"])
    ).json()
    assert me["role"] == "manager"


def test_cannot_invite_an_existing_member_of_the_same_tenant(admin_token: str) -> None:
    r = client.post(
        "/api/v1/members/invite",
        json={"email": _ADMIN["email"], "role": "manager"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 409


def test_admin_can_revoke_a_pending_invite(admin_token: str) -> None:
    invite = client.post(
        "/api/v1/members/invite",
        json={"email": "revoke-me@example.com", "role": "member"},
        headers=_auth(admin_token),
    ).json()

    r = client.delete(f"/api/v1/members/invites/{invite['id']}", headers=_auth(admin_token))
    assert r.status_code == 204

    r2 = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite["invite_token"], "password": "somepassword1"},
    )
    assert r2.status_code == 401


def test_accept_invite_with_bad_token_returns_401() -> None:
    r = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": "not-a-real-token", "password": "somepassword1"},
    )
    assert r.status_code == 401


def test_inviting_the_same_email_again_replaces_the_old_invite(admin_token: str) -> None:
    first = client.post(
        "/api/v1/members/invite",
        json={"email": "reissue@example.com", "role": "member"},
        headers=_auth(admin_token),
    ).json()
    second = client.post(
        "/api/v1/members/invite",
        json={"email": "Reissue@Example.com", "role": "manager"},
        headers=_auth(admin_token),
    ).json()

    pending = client.get("/api/v1/members/invites", headers=_auth(admin_token)).json()
    mine = [i for i in pending if i["email"] == "reissue@example.com"]
    assert [i["id"] for i in mine] == [second["id"]]
    assert mine[0]["role"] == "manager"

    old = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": first["invite_token"], "password": "somepassword1"},
    )
    assert old.status_code == 401

    client.delete(f"/api/v1/members/invites/{second['id']}", headers=_auth(admin_token))
