"""Audit-log list filters and paging (FR-TEN-06)."""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db.engine as db_engine
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
_ADMIN = {"email": "alog-admin@example.com", "password": "alogadmin12345", "tenant_name": "Alog Co"}


def _wipe() -> None:
    async def go() -> None:
        async with db_engine.AsyncSessionLocal() as s:
            await s.execute(text("DELETE FROM tenants WHERE slug = 'alog-co'"))
            await s.execute(text("DELETE FROM users WHERE email = 'alog-admin@example.com'"))
            await s.commit()

    asyncio.run(go())


@pytest.fixture(scope="module")
def headers() -> dict[str, str]:
    _wipe()
    client.post("/api/v1/auth/register", json=_ADMIN)
    r = client.post(
        "/api/v1/auth/login", json={"email": _ADMIN["email"], "password": _ADMIN["password"]}
    )
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for name in ("One", "Two"):
        assert client.post("/api/v1/clients", json={"name": name}, headers=h).status_code == 201
    yield h  # type: ignore[misc]
    _wipe()


def test_filters_by_action_and_entity_and_pages_with_a_cursor(headers: dict[str, str]) -> None:
    url = "/api/v1/audit-log"
    created = client.get(url, params={"action": "client.created"}, headers=headers).json()["items"]
    assert len(created) == 2 and {i["action"] for i in created} == {"client.created"}
    assert client.get(url, params={"action": "no.such"}, headers=headers).json()["items"] == []
    by_entity = client.get(url, params={"entity": created[0]["entity"]}, headers=headers).json()
    assert by_entity["items"]

    p1 = client.get(url, params={"limit": 1}, headers=headers).json()
    assert len(p1["items"]) == 1 and p1["next_cursor"]
    p2 = client.get(url, params={"limit": 1, "cursor": p1["next_cursor"]}, headers=headers).json()
    assert p2["items"] and p2["items"][0]["id"] != p1["items"][0]["id"]


def test_a_bad_cursor_is_a_400(headers: dict[str, str]) -> None:
    r = client.get("/api/v1/audit-log", params={"cursor": "junk"}, headers=headers)
    assert r.status_code == 400
