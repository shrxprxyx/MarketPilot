"""
/me identity fields and the agency list behind the web app's switcher.

`/me` now also returns the caller's email and the active agency's name.
`GET /me/tenants` lists every agency the caller has an ACTIVE membership in, so
the UI can offer a switcher. A user with two agencies is built the same way as
tests/test_switch_tenant.py: invite an existing admin into a second tenant.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db.engine as db_engine
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_PRIMARY = {
    "email": "me-primary@example.com",
    "password": "meprimarypass1",
    "tenant_name": "Me Primary Co",
}
_SECONDARY = {
    "email": "me-secondary@example.com",
    "password": "mesecondarypass1",
    "tenant_name": "Me Secondary Co",
}
_TEST_EMAILS = (_PRIMARY["email"], _SECONDARY["email"])
_TEST_SLUGS = ("me-primary-co", "me-secondary-co")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(creds: dict) -> str:
    client.post("/api/v1/auth/register", json=creds)  # may already exist
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            slugs = ", ".join(f"'{s}'" for s in _TEST_SLUGS)
            await session.execute(text(f"DELETE FROM tenants WHERE slug IN ({slugs})"))
            emails = ", ".join(f"'{e}'" for e in _TEST_EMAILS)
            await session.execute(text(f"DELETE FROM users WHERE email IN ({emails})"))
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def primary_token() -> str:
    return _login(_PRIMARY)


@pytest.fixture(scope="module")
def secondary_token() -> str:
    return _login(_SECONDARY)


@pytest.fixture(scope="module")
def two_agency_user(primary_token: str, secondary_token: str) -> str:
    """Invites the primary admin into the secondary tenant as a manager."""
    invite = client.post(
        "/api/v1/members/invite",
        json={"email": _PRIMARY["email"], "role": "manager"},
        headers=_auth(secondary_token),
    ).json()
    accept = client.post(
        "/api/v1/auth/accept-invite",
        json={"token": invite["invite_token"], "password": _PRIMARY["password"]},
    )
    assert accept.status_code == 200, accept.text
    return primary_token


def test_me_includes_email_and_tenant_name(primary_token: str) -> None:
    r = client.get("/api/v1/me", headers=_auth(primary_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == _PRIMARY["email"]
    assert body["tenant_name"] == _PRIMARY["tenant_name"]
    assert body["role"] == "admin"
    assert {"user_id", "tenant_id"} <= body.keys()


def test_me_tenants_requires_authentication() -> None:
    assert client.get("/api/v1/me/tenants").status_code == 401


def test_me_tenants_lists_only_the_callers_own_agency(secondary_token: str) -> None:
    # Runs before the invite fixture is requested for this user's own list.
    r = client.get("/api/v1/me/tenants", headers=_auth(secondary_token))
    assert r.status_code == 200, r.text
    names = {t["name"] for t in r.json()}
    assert _PRIMARY["tenant_name"] not in names
    assert _SECONDARY["tenant_name"] in names


def test_me_tenants_lists_every_active_membership_with_role(
    two_agency_user: str,
) -> None:
    r = client.get("/api/v1/me/tenants", headers=_auth(two_agency_user))
    assert r.status_code == 200, r.text
    by_name = {t["name"]: t for t in r.json()}
    assert set(by_name) == {_PRIMARY["tenant_name"], _SECONDARY["tenant_name"]}
    assert by_name[_PRIMARY["tenant_name"]]["role"] == "admin"
    assert by_name[_SECONDARY["tenant_name"]]["role"] == "manager"
    # id matches what /auth/switch-tenant expects.
    me = client.get("/api/v1/me", headers=_auth(two_agency_user)).json()
    assert by_name[_PRIMARY["tenant_name"]]["id"] == me["tenant_id"]


def test_me_tenants_omits_deactivated_memberships(
    two_agency_user: str, secondary_token: str
) -> None:
    members = client.get("/api/v1/members", headers=_auth(secondary_token)).json()["items"]
    invited = next(m for m in members if m["email"] == _PRIMARY["email"])
    patched = client.patch(
        f"/api/v1/members/{invited['id']}",
        json={"status": "deactivated"},
        headers=_auth(secondary_token),
    )
    assert patched.status_code == 200, patched.text

    r = client.get("/api/v1/me/tenants", headers=_auth(two_agency_user))
    assert r.status_code == 200, r.text
    assert [t["name"] for t in r.json()] == [_PRIMARY["tenant_name"]]
