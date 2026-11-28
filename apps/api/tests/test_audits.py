"""Audits API and runner (FR-AUD-01, 06). The site is served by a mock transport and the Celery
hand-off is captured, so the runner is executed explicitly and nothing touches the network.
"""
import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.api.v1.audits as audits_api
import app.audit.runner as runner
import app.db.engine as db_engine
from app.audit.fetcher import SafeFetcher
from app.audit.runner import run_audit
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.main import app
from app.models.membership import Membership
from app.models.user import User
from tests.test_audit_engine import allow_all, home, site

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {"email": "aud-admin@example.com", "password": "audadmin12345", "tenant_name": "Aud Co"}
_OTHER = {"email": "aud-other@example.com", "password": "audother12345", "tenant_name": "Aud Two"}

BROKEN_SITE: dict[str, httpx.Response | str] = {
    "/": home("/missing"),
    "/missing": httpx.Response(404, text="gone"),
}

_queued: list[tuple[UUID, UUID, UUID]] = []
_routes: dict[str, dict[str, httpx.Response | str]] = {"site": BROKEN_SITE}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(creds: dict[str, str]) -> str:
    client.post("/api/v1/auth/register", json=creds)
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


async def _member_token(tenant_id: UUID) -> str:
    async with db_engine.AsyncSessionLocal() as session:
        user = User(email="aud-member@example.com", hashed_password=hash_password("x-irrelevant-1"))
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="member"))
        await session.commit()
        return create_access_token(user.id, tenant_id, "member")


def _run_queued() -> None:
    async def _go(tenant_id: UUID, audit_id: UUID, job_id: UUID) -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await run_audit(session, tenant_id, audit_id, job_id)

    while _queued:
        asyncio.run(_go(*_queued.pop()))


@pytest.fixture(autouse=True)
def _fake_world(monkeypatch: pytest.MonkeyPatch) -> None:
    _queued.clear()
    _routes["site"] = BROKEN_SITE
    monkeypatch.setattr(runner.settings, "pagespeed_api_key", "")  # never call Google from tests
    monkeypatch.setattr(
        audits_api, "enqueue_website_audit", lambda t, a, j: _queued.append((t, a, j))
    )
    monkeypatch.setattr(
        runner, "SafeFetcher",
        lambda: SafeFetcher(check=allow_all, transport=site(_routes["site"]), min_interval=0),
    )


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE slug IN ('aud-co', 'aud-two')")
            )
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN ('aud-admin@example.com', "
                    "'aud-other@example.com', 'aud-member@example.com')"
                )
            )
            await session.commit()

    asyncio.run(_delete())
    yield  # type: ignore[misc]
    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _register(_ADMIN)


@pytest.fixture(scope="module")
def other_token() -> str:
    return _register(_OTHER)


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    return UUID(client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_id"])


def _new_client(token: str, **body: Any) -> str:
    body.setdefault("name", "Acme")
    r = client.post("/api/v1/clients", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


@pytest.fixture
def cid(admin_token: str) -> str:
    return _new_client(admin_token, website_url="https://acme.test")


def _start(token: str, client_id: str, **headers: str) -> Any:
    return client.post(
        f"/api/v1/clients/{client_id}/audits", json={"type": "website"},
        headers={**_auth(token), **headers},
    )


def _job(token: str, job_id: str) -> dict[str, Any]:
    r = client.get(f"/api/v1/jobs/{job_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    return dict(r.json())


# ---------- starting an audit ----------


def test_start_queues_an_audit_and_a_job(admin_token: str, cid: str, tenant_id: UUID) -> None:
    r = _start(admin_token, cid)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["url"] == "https://acme.test"
    assert body["type"] == "website"
    assert _queued == [(tenant_id, UUID(body["id"]), UUID(body["job_id"]))]
    assert _job(admin_token, body["job_id"])["status"] == "queued"


def test_the_list_gives_the_job_of_an_audit_that_is_still_active(
    admin_token: str, cid: str
) -> None:
    started = _start(admin_token, cid).json()
    listed = client.get(f"/api/v1/clients/{cid}/audits", headers=_auth(admin_token)).json()
    assert listed["items"][0]["id"] == started["id"]
    assert listed["items"][0]["job_id"] == started["job_id"]


def test_start_needs_a_website_and_an_active_client(admin_token: str) -> None:
    no_site = _new_client(admin_token, name="No site")
    r = _start(admin_token, no_site)
    assert r.status_code == 422
    assert "website URL" in r.json()["detail"]

    archived = _new_client(admin_token, name="Old", website_url="https://old.test")
    client.patch(
        f"/api/v1/clients/{archived}", json={"status": "archived"}, headers=_auth(admin_token)
    )
    r = _start(admin_token, archived)
    assert r.status_code == 409
    assert "Restore" in r.json()["detail"]
    assert _queued == []


def test_only_one_audit_runs_per_client_at_a_time(admin_token: str, cid: str) -> None:
    assert _start(admin_token, cid).status_code == 202
    again = _start(admin_token, cid)
    assert again.status_code == 409
    assert "already running" in again.json()["detail"]
    _run_queued()
    assert _start(admin_token, cid).status_code == 202  # fine once the first one finished


def test_a_retried_post_with_the_same_key_returns_the_same_audit(
    admin_token: str, cid: str
) -> None:
    first = _start(admin_token, cid, **{"Idempotency-Key": "audit-key-0001"})
    second = _start(admin_token, cid, **{"Idempotency-Key": "audit-key-0001"})
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["job_id"] == first.json()["job_id"]
    assert len(_queued) == 1


def test_members_can_read_but_not_start_audits(admin_token: str, cid: str, tenant_id: UUID) -> None:
    member = asyncio.run(_member_token(tenant_id))
    assert _start(member, cid).status_code == 403
    audit_id = _start(admin_token, cid).json()["id"]
    assert client.get(f"/api/v1/audits/{audit_id}", headers=_auth(member)).status_code == 200
    assert client.get(f"/api/v1/clients/{cid}/audits", headers=_auth(member)).status_code == 200


def test_a_broken_queue_marks_the_audit_failed_instead_of_erroring(
    admin_token: str, cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: Any) -> None:
        raise RuntimeError("no broker")

    monkeypatch.setattr(audits_api, "enqueue_website_audit", boom)
    r = _start(admin_token, cid)
    assert r.status_code == 202
    assert r.json()["status"] == "failed"
    assert "queue" in r.json()["error"]
    assert _job(admin_token, r.json()["job_id"])["status"] == "failed"
    assert _start(admin_token, cid).status_code == 202  # a failed audit does not block the next


# ---------- running ----------


def test_a_run_stores_a_score_and_sorted_findings(admin_token: str, cid: str) -> None:
    started = _start(admin_token, cid).json()
    _run_queued()

    audit = client.get(f"/api/v1/audits/{started['id']}", headers=_auth(admin_token)).json()
    assert audit["status"] == "succeeded"
    assert 0 <= audit["score"]

def test_findings_can_be_filtered_by_severity_and_category(admin_token: str, cid: str) -> None:
    audit_id = _start(admin_token, cid).json()["id"]
    _run_queued()
    url = f"/api/v1/audits/{audit_id}/findings"
    everything = client.get(url, headers=_auth(admin_token)).json()["items"]
    assert everything
    sev = everything[0]["severity"]
    only_sev = client.get(url, params={"severity": sev}, headers=_auth(admin_token)).json()["items"]
    assert only_sev and {f["severity"] for f in only_sev} == {sev}
    only_cat = client.get(
        url, params={"category": "mobile"}, headers=_auth(admin_token)
    ).json()["items"]
    assert all(f["category"] == "mobile" for f in only_cat)


def test_comparison_needs_a_finished_audit_and_diffs_against_the_previous(
    admin_token: str, cid: str
) -> None:
    first = _start(admin_token, cid).json()["id"]
    cmp_url = "/api/v1/audits/{}/comparison"
    # still queued: cannot be compared
    assert client.get(cmp_url.format(first), headers=_auth(admin_token)).status_code == 409
    _run_queued()
    r = client.get(cmp_url.format(first), headers=_auth(admin_token)).json()
    assert r["previous"] is None and r["new"] == [] and r["fixed"] == []

    _routes["site"] = {"/": home()}  # the broken link is fixed
    second = _start(admin_token, cid).json()["id"]
    _run_queued()
    r = client.get(cmp_url.format(second), headers=_auth(admin_token)).json()
    assert r["previous"]["id"] == first
    assert any(f["code"] for f in r["fixed"])


def test_the_audit_list_pages_with_a_cursor_and_rejects_a_bad_one(
    admin_token: str, cid: str
) -> None:
    ids = []
    for _ in range(2):
        ids.append(_start(admin_token, cid).json()["id"])
        _run_queued()
    url = f"/api/v1/clients/{cid}/audits"
    page1 = client.get(url, params={"limit": 1}, headers=_auth(admin_token)).json()
    assert [a["id"] for a in page1["items"]] == [ids[1]]
    assert page1["next_cursor"]
    page2 = client.get(
        url, params={"limit": 1, "cursor": page1["next_cursor"]}, headers=_auth(admin_token)
    ).json()
    assert [a["id"] for a in page2["items"]] == [ids[0]]
    bad = client.get(url, params={"cursor": "nope"}, headers=_auth(admin_token))
    assert bad.status_code == 400


def test_an_audit_cancelled_before_it_starts_is_marked_cancelled(
    admin_token: str, cid: str
) -> None:
    started = _start(admin_token, cid).json()
    r = client.delete(f"/api/v1/jobs/{started['job_id']}", headers=_auth(admin_token))
    assert r.status_code == 200
    _run_queued()
    audit = client.get(f"/api/v1/audits/{started['id']}", headers=_auth(admin_token)).json()
    assert audit["status"] == "cancelled"


def test_an_unexpected_crash_fails_the_audit_and_its_job(
    admin_token: str, cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("crawler exploded")

    monkeypatch.setattr(runner, "crawl", boom)
    started = _start(admin_token, cid).json()
    _run_queued()
    audit = client.get(f"/api/v1/audits/{started['id']}", headers=_auth(admin_token)).json()
    assert audit["status"] == "failed"
    assert _job(admin_token, started["job_id"])["status"] == "failed"


def test_a_run_with_a_key_stores_pagespeed_results_and_mobile_findings(
    admin_token: str, cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(crawl_result: Any, key: str, **_: Any) -> Any:
        from app.audit.checks import Finding

        return (
            {"status": "done", "results": []},
            [Finding(code="lh_font_size", category="mobile", severity="medium",
                     title="Text is too small", detail="d", recommendation="r",
                     url=crawl_result.start_url)],
        )

    monkeypatch.setattr(runner, "collect_pagespeed", fake)
    started = _start(admin_token, cid).json()
    _run_queued()
    audit = client.get(f"/api/v1/audits/{started['id']}", headers=_auth(admin_token)).json()
    assert audit["status"] == "succeeded"
    assert audit["summary"]["pagespeed"]["status"] == "done"
    mobile = client.get(
        f"/api/v1/audits/{started['id']}/findings",
        params={"category": "mobile"}, headers=_auth(admin_token),
    ).json()["items"]
    assert [f["code"] for f in mobile] == ["lh_font_size"]


def _status(token: str, audit_id: str) -> str:
    return str(client.get(f"/api/v1/audits/{audit_id}", headers=_auth(token)).json()["status"])


def test_a_crawl_that_was_cancelled_marks_the_audit_cancelled(
    admin_token: str, cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def cancelled_crawl(*_: Any, **__: Any) -> Any:
        return SimpleNamespace(cancelled=True)

    monkeypatch.setattr(runner, "crawl", cancelled_crawl)
    started = _start(admin_token, cid).json()
    _run_queued()
    assert _status(admin_token, started["id"]) == "cancelled"


def test_cancelling_during_the_pagespeed_step_stops_before_scoring(
    admin_token: str, cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = {"now": False}

    async def fake_speed(_crawl: Any, _key: str, *, on_progress: Any, **__: Any) -> Any:
        await on_progress(0, 2)  # the runner's progress callback
        stop["now"] = True
        return {"status": "done", "results": []}, []

    async def is_cancelled(*_: Any) -> bool:
        return stop["now"]

    monkeypatch.setattr(runner, "collect_pagespeed", fake_speed)
    monkeypatch.setattr(runner, "is_cancelled", is_cancelled)
    started = _start(admin_token, cid).json()
    _run_queued()
    assert _status(admin_token, started["id"]) == "cancelled"
    findings = client.get(f"/api/v1/audits/{started['id']}/findings", headers=_auth(admin_token))
    assert findings.json()["items"] == []


def test_an_audit_that_no_longer_exists_cancels_its_job(
    admin_token: str, cid: str, tenant_id: UUID
) -> None:
    started = _start(admin_token, cid).json()
    _queued.clear()

    async def go() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await run_audit(session, tenant_id, uuid4(), UUID(started["job_id"]))

    asyncio.run(go())
    assert _job(admin_token, started["job_id"])["status"] == "cancelled"
