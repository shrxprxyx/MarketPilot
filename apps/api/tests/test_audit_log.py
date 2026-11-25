"""
Audit log (FR-TEN-06).

Security-relevant actions (login, role change, invite created, member removed,
client archived, ...) get written to audit_log. Verifies entries actually show
up with the right action/entity, that only admins can read the log, and that
it's genuinely immutable — not just "the app never calls UPDATE/DELETE," but
that Postgres itself refuses those statements (already proven once at the DB
level during development; this exercises the same guarantee through the API's
own session).
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db.engine as db_engine
from app.db.rls import set_rls_context
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {
    "email": "audit-admin@example.com",
    "password": "auditadmin1",
    "tenant_name": "Audit Co",
}
_TEST_EMAILS = (
    "audit-admin@example.com",
    "audit-member@example.com",
    "audit-joiner@example.com",
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
            await session.execute(text("DELETE FROM tenants WHERE slug = 'audit-co'"))
            emails = ", ".join(f"'{e}'" for e in _TEST_EMAILS)
            await session.execute(text(f"DELETE FROM users WHERE email IN ({emails})"))
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    # register() itself writes an audit entry ("register"), which the
    # test_register_and_login_are_both_logged test below asserts on.
    return _register(_ADMIN)["access_token"]


def test_only_admin_can_read_audit_log(admin_token: str) -> None:
    async def _seed_member() -> str:
        from app.auth.jwt import create_access_token
        from app.auth.password import hash_password
        from app.models.membership import Membership
        from app.models.user import User

        me = client.get("/api/v1/me", headers=_auth(admin_token)).json()
        tenant_id = me["tenant_id"]
        async with db_engine.AsyncSessionLocal() as session:
            user = User(
                email="audit-member@example.com", hashed_password=hash_password("irrelevant1234")
            )
            session.add(user)
            await session.flush()
            await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
            session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="member"))
            await session.commit()
            uid = user.id
        return create_access_token(uid, tenant_id, "member")

    member_token = asyncio.run(_seed_member())
    r = client.get("/api/v1/audit-log", headers=_auth(member_token))
    assert r.status_code == 403


def test_register_and_login_are_both_logged(admin_token: str) -> None:
    client.post(
        "/api/v1/auth/login", json={"email": _ADMIN["email"], "password": _ADMIN["password"]}
    )

    entries = client.get("/api/v1/audit-log", headers=_auth(admin_token)).json()["items"]
    actions = [e["action"] for e in entries]
    assert "register" in actions
    assert "login" in actions


def test_role_change_and_member_removal_are_logged(admin_token: str) -> None:
    me = client.get("/api/v1/me", headers=_auth(admin_token)).json()
    tenant_id = me["tenant_id"]

    async def _seed() -> str:
        from app.auth.password import hash_password
        from app.models.membership import Membership
        from app.models.user import User

        async with db_engine.AsyncSessionLocal() as session:
            user = User(
                email="audit-promote@example.com", hashed_password=hash_password("irrelevant1234")
            )
            session.add(user)
            await session.flush()
            await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
            membership = Membership(user_id=user.id, tenant_id=tenant_id, role="member")
            session.add(membership)
            await session.commit()
            return str(membership.id)

    membership_id = asyncio.run(_seed())

    client.patch(
        f"/api/v1/members/{membership_id}", json={"role": "manager"}, headers=_auth(admin_token)
    )
    client.delete(f"/api/v1/members/{membership_id}", headers=_auth(admin_token))

    entries = client.get(
        "/api/v1/audit-log", params={"limit": 50}, headers=_auth(admin_token)
    ).json()["items"]
    role_change = next(e for e in entries if e["action"] == "member.updated")
    assert role_change["meta"]["role_to"] == "manager"
    removal = next(e for e in entries if e["action"] == "member.removed")
    assert removal["entity_id"] == membership_id

    async def _cleanup_promote_user() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM users WHERE email = 'audit-promote@example.com'")
            )
            await session.commit()

    asyncio.run(_cleanup_promote_user())


def test_invite_created_and_client_archived_are_logged(admin_token: str) -> None:
    invite = client.post(
        "/api/v1/members/invite",
        json={"email": "audit-invitee@example.com", "role": "member"},
        headers=_auth(admin_token),
    ).json()
    created_client = client.post(
        "/api/v1/clients", json={"name": "Audited Co"}, headers=_auth(admin_token)
    ).json()
    client.delete(f"/api/v1/clients/{created_client['id']}", headers=_auth(admin_token))

    entries = client.get(
        "/api/v1/audit-log", params={"limit": 50}, headers=_auth(admin_token)
    ).json()["items"]
    invite_entry = next(e for e in entries if e["action"] == "invite.created")
    assert invite_entry["meta"]["email"] == "audit-invitee@example.com"
    assert invite_entry["entity_id"] == invite["id"]
    archive_entry = next(e for e in entries if e["action"] == "client.archived")
    assert archive_entry["entity_id"] == created_client["id"]

    client.delete(f"/api/v1/members/invites/{invite['id']}", headers=_auth(admin_token))


def test_accepted_invite_is_logged_against_the_new_membership(admin_token: str) -> None:
    invite = client.post(
        "/api/v1/members/invite",
        json={"email": "audit-joiner@example.com", "role": "member"},
        headers=_auth(admin_token),
    ).json()
    accepted = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite["invite_token"], "password": "password123"},
    )
    assert accepted.status_code == 200, accepted.text

    entries = client.get(
        "/api/v1/audit-log", params={"limit": 50}, headers=_auth(admin_token)
    ).json()["items"]
    entry = next(e for e in entries if e["action"] == "invite.accepted")
    members = client.get("/api/v1/members", headers=_auth(admin_token)).json()
    joiner = next(m for m in members if m["email"] == "audit-joiner@example.com")
    assert entry["entity"] == "membership"
    assert entry["entity_id"] == joiner["id"]


def test_audit_log_filters_by_action(admin_token: str) -> None:
    entries = client.get(
        "/api/v1/audit-log", params={"action": "login", "limit": 50}, headers=_auth(admin_token)
    ).json()["items"]
    assert entries
    assert all(e["action"] == "login" for e in entries)


def test_cross_tenant_audit_log_is_isolated(admin_token: str) -> None:
    other = _register(
        {
            "email": "audit-other-admin@example.com",
            "password": "otheradmin123",
            "tenant_name": "Other Audit Co",
        }
    )
    other_entries = client.get("/api/v1/audit-log", headers=_auth(other["access_token"])).json()
    my_entries = client.get("/api/v1/audit-log", headers=_auth(admin_token)).json()

    my_ids = {e["id"] for e in my_entries["items"]}
    other_ids = {e["id"] for e in other_entries["items"]}
    assert my_ids.isdisjoint(other_ids)

    async def _cleanup_other() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM tenants WHERE slug = 'other-audit-co'"))
            await session.execute(
                text("DELETE FROM users WHERE email = 'audit-other-admin@example.com'")
            )
            await session.commit()

    asyncio.run(_cleanup_other())


async def test_audit_log_rows_cannot_be_updated_or_deleted(admin_token: str) -> None:
    """Even through the app's own (app_user) session, RLS has no UPDATE/DELETE
    policy on audit_log at all — these statements must affect zero rows."""
    entries = client.get("/api/v1/audit-log", headers=_auth(admin_token)).json()["items"]
    assert entries
    target_id = entries[0]["id"]

    me = client.get("/api/v1/me", headers=_auth(admin_token)).json()
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=me["tenant_id"])

        result = await session.execute(
            text("UPDATE audit_log SET action = 'tampered' WHERE id = :id"),
            {"id": target_id},
        )
        assert result.rowcount == 0

        result = await session.execute(
            text("DELETE FROM audit_log WHERE id = :id"), {"id": target_id}
        )
        assert result.rowcount == 0
        await session.rollback()


def test_client_create_update_and_logout_are_logged(admin_token: str) -> None:
    created = client.post(
        "/api/v1/clients", json={"name": "Audited Client"}, headers=_auth(admin_token)
    )
    assert created.status_code == 201, created.text
    client_id = created.json()["id"]
    r = client.patch(
        f"/api/v1/clients/{client_id}", json={"industry": "SaaS"}, headers=_auth(admin_token)
    )
    assert r.status_code == 200, r.text

    login = client.post(
        "/api/v1/auth/login", json={"email": _ADMIN["email"], "password": _ADMIN["password"]}
    ).json()
    out = client.post("/api/v1/auth/logout", json={"refresh_token": login["refresh_token"]})
    assert out.status_code == 204

    entries = client.get(
        "/api/v1/audit-log", params={"limit": 100}, headers=_auth(admin_token)
    ).json()["items"]
    by_action: dict[str, dict] = {}
    for e in entries:  # newest first; keep the most recent entry per action
        by_action.setdefault(e["action"], e)
    assert by_action["client.created"]["entity_id"] == client_id
    assert by_action["client.updated"]["meta"]["fields"] == ["industry"]
    assert "logout" in by_action
