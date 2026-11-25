"""
Tenant switching (FR-AUTH-05).

A user with several memberships can switch the active tenant and get a new
token pair for it. This is also the regression test for a real bug: before
this feature, login()/refresh() assumed exactly one membership per user —
`db.scalar()` on a query matching more than one row raises MultipleResultsFound.
Multi-membership users are created here by inviting the same existing admin
into a second tenant (the same mechanism tests/test_invites.py already proves).
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db.engine as db_engine
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_PRIMARY_ADMIN = {
    "email": "switch-primary@example.com",
    "password": "switchprimary1",
    "tenant_name": "Switch Primary Co",
}
_SECONDARY_ADMIN = {
    "email": "switch-secondary@example.com",
    "password": "switchsecondary1",
    "tenant_name": "Switch Secondary Co",
}
_TEST_EMAILS = (
    "switch-primary@example.com",
    "switch-secondary@example.com",
)
_TEST_SLUGS = ("switch-primary-co", "switch-secondary-co")


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
            placeholders = ", ".join(f"'{s}'" for s in _TEST_SLUGS)
            await session.execute(text(f"DELETE FROM tenants WHERE slug IN ({placeholders})"))
            emails = ", ".join(f"'{e}'" for e in _TEST_EMAILS)
            await session.execute(text(f"DELETE FROM users WHERE email IN ({emails})"))
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def primary() -> dict:
    """Returns dict with tenant_id, membership emails etc for the primary tenant."""
    tokens = _register(_PRIMARY_ADMIN)
    me = client.get("/api/v1/me", headers=_auth(tokens["access_token"])).json()
    return {"tokens": tokens, "tenant_id": me["tenant_id"]}


@pytest.fixture(scope="module")
def secondary_tenant_id(primary: dict) -> str:
    """Registers a second tenant and invites the primary admin's email into it,
    so that one real user ends up with two active memberships."""
    secondary_tokens = _register(_SECONDARY_ADMIN)
    secondary_me = client.get(
        "/api/v1/me", headers=_auth(secondary_tokens["access_token"])
    ).json()

    invite = client.post(
        "/api/v1/members/invite",
        json={"email": _PRIMARY_ADMIN["email"], "role": "manager"},
        headers=_auth(secondary_tokens["access_token"]),
    ).json()
    accept = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite["invite_token"], "password": _PRIMARY_ADMIN["password"]},
    )
    assert accept.status_code == 200, accept.text

    return secondary_me["tenant_id"]


def test_login_no_longer_crashes_for_multi_membership_user(
    primary: dict, secondary_tenant_id: str
) -> None:
    """Regression test: this used to raise MultipleResultsFound."""
    r = client.post(
        "/api/v1/auth/login",
        json={"email": _PRIMARY_ADMIN["email"], "password": _PRIMARY_ADMIN["password"]},
    )
    assert r.status_code == 200, r.text


def test_login_picks_oldest_membership_deterministically(
    primary: dict, secondary_tenant_id: str
) -> None:
    r = client.post(
        "/api/v1/auth/login",
        json={"email": _PRIMARY_ADMIN["email"], "password": _PRIMARY_ADMIN["password"]},
    )
    me = client.get("/api/v1/me", headers=_auth(r.json()["access_token"])).json()
    # The primary tenant (registered first) is the older membership.
    assert me["tenant_id"] == primary["tenant_id"]
    assert me["role"] == "admin"


def test_switch_tenant_moves_to_the_other_active_membership(
    primary: dict, secondary_tenant_id: str
) -> None:
    r = client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": secondary_tenant_id},
        headers=_auth(primary["tokens"]["access_token"]),
    )
    assert r.status_code == 200, r.text
    tokens = r.json()

    me = client.get("/api/v1/me", headers=_auth(tokens["access_token"])).json()
    assert me["tenant_id"] == secondary_tenant_id
    assert me["role"] == "manager"  # role invited as, in the secondary tenant


def test_switch_tenant_rejects_tenant_not_a_member_of(primary: dict) -> None:
    r = client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": "00000000-0000-0000-0000-000000000000"},
        headers=_auth(primary["tokens"]["access_token"]),
    )
    assert r.status_code == 403


def test_refresh_resumes_the_exact_tenant_it_was_issued_for(
    primary: dict, secondary_tenant_id: str
) -> None:
    switched = client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": secondary_tenant_id},
        headers=_auth(primary["tokens"]["access_token"]),
    ).json()

    refreshed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": switched["refresh_token"]}
    )
    assert refreshed.status_code == 200, refreshed.text

    me = client.get("/api/v1/me", headers=_auth(refreshed.json()["access_token"])).json()
    # Must stay on the secondary tenant, not fall back to the primary one.
    assert me["tenant_id"] == secondary_tenant_id


def test_deactivating_a_membership_blocks_switching_to_it(
    primary: dict, secondary_tenant_id: str
) -> None:
    secondary_admin_token = _register(_SECONDARY_ADMIN)["access_token"]
    members = client.get(
        "/api/v1/members", headers=_auth(secondary_admin_token)
    ).json()["items"]
    target = next(m for m in members if m["email"] == _PRIMARY_ADMIN["email"])

    client.patch(
        f"/api/v1/members/{target['id']}",
        json={"status": "deactivated"},
        headers=_auth(secondary_admin_token),
    )

    r = client.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": secondary_tenant_id},
        headers=_auth(primary["tokens"]["access_token"]),
    )
    assert r.status_code == 403
