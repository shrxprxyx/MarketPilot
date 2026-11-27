"""Audits API and runner (FR-AUD-01, 06). The site is served by a mock transport and the Celery
hand-off is captured, so the runner is executed explicitly and nothing touches the network."""
import asyncio
from typing import Any
from uuid import UUID

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
from app.jobs.progress import update_job
from app.main import app
from app.models.membership import Membership
from app.models.user import User
from tests.test_audit_engine import CLEAN_SITE, allow_all, home, site

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
    assert 0 <= audit["score"] < 100
    assert audit["finished_at"] and audit["started_at"]
    summary = audit["summary"]
    assert summary["pages_crawled"] == 2
    assert set(summary["categories"]) == {"technical", "on_page", "links", "mobile"}
    assert summary["severity_counts"]["high"] >= 1

    job = _job(admin_token, started["job_id"])
    assert job["status"] == "succeeded"
    assert job["progress"] == 100
    assert job["result_ref"]["audit_id"] == started["id"]

    findings = client.get(
        f"/api/v1/audits/{started['id']}/findings", headers=_auth(admin_token)
    ).json()["items"]
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    assert [rank[f["severity"]] for f in findings] == sorted(rank[f["severity"]] for f in findings)
    broken = next(f for f in findings if f["code"] == "broken_internal_link")
    assert broken["url"] == "https://acme.test/missing"
    assert broken["recommendation"]
    assert sum(summary["severity_counts"].values()) == len(findings)


def test_findings_can_be_filtered(admin_token: str, cid: str) -> None:
    audit_id = _start(admin_token, cid).json()["id"]
    _run_queued()
    base = f"/api/v1/audits/{audit_id}/findings"
    high = client.get(base, params={"severity": "high"}, headers=_auth(admin_token)).json()
    assert high["items"]
    assert {f["severity"] for f in high["items"]} == {"high"}
    links = client.get(base, params={"category": "links"}, headers=_auth(admin_token)).json()
    assert {f["category"] for f in links["items"]} == {"links"}
    bad = client.get(base, params={"severity": "nope"}, headers=_auth(admin_token))
    assert bad.status_code == 422


def test_a_clean_site_scores_high_with_no_findings(admin_token: str, cid: str) -> None:
    _routes["site"] = CLEAN_SITE
    audit_id = _start(admin_token, cid).json()["id"]
    _run_queued()
    audit = client.get(f"/api/v1/audits/{audit_id}", headers=_auth(admin_token)).json()
    assert audit["score"] == 100
    items = client.get(
        f"/api/v1/audits/{audit_id}/findings", headers=_auth(admin_token)
    ).json()["items"]
    assert items == []


def test_a_cancelled_job_stops_the_audit(
    admin_token: str, cid: str, tenant_id: UUID
) -> None:
    started = _start(admin_token, cid).json()
    r = client.delete(f"/api/v1/jobs/{started['job_id']}", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    _run_queued()
    audit = client.get(f"/api/v1/audits/{started['id']}", headers=_auth(admin_token)).json()
    assert audit["status"] == "cancelled"
    assert audit["score"] is None
    assert client.get(
        f"/api/v1/audits/{started['id']}/findings", headers=_auth(admin_token)
    ).json()["items"] == []


def test_cancelling_mid_crawl_stops_it_at_the_next_page(
    admin_token: str, cid: str, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    _routes["site"] = {"/": home("/a", "/b"), "/a": home(), "/b": home(), **{
        k: v for k, v in CLEAN_SITE.items() if k in ("/robots.txt", "/sitemap.xml")
    }}
    started = _start(admin_token, cid).json()
    real = runner.update_job
    pages = 0

    async def cancel_after_first_page(*a: Any, **kw: Any) -> Any:
        nonlocal pages
        if kw.get("message", "").startswith("Crawled"):
            pages += 1
            if pages == 1:
                await update_job(a[0], a[1], a[2], status="cancelled", message="Cancelled.")
        return await real(*a, **kw)

    monkeypatch.setattr(runner, "update_job", cancel_after_first_page)
    _run_queued()
    audit = client.get(f"/api/v1/audits/{started['id']}", headers=_auth(admin_token)).json()
    assert audit["status"] == "cancelled"
    assert pages == 1


def test_an_unexpected_crash_is_reported_not_raised(
    admin_token: str, cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def crash(*_: Any, **__: Any) -> Any:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(runner, "crawl", crash)
    started = _start(admin_token, cid).json()
    _run_queued()
    audit = client.get(f"/api/v1/audits/{started['id']}", headers=_auth(admin_token)).json()
    assert audit["status"] == "failed"
    assert "exploded" not in str(audit)  # internals are not leaked
    assert _job(admin_token, started["job_id"])["status"] == "failed"


# ---------- history and isolation ----------


def test_history_lists_newest_first_with_a_cursor(admin_token: str, cid: str) -> None:
    ids = []
    for _ in range(3):
        ids.append(_start(admin_token, cid).json()["id"])
        _run_queued()
    page1 = client.get(
        f"/api/v1/clients/{cid}/audits", params={"limit": 2}, headers=_auth(admin_token)
    ).json()
    assert [a["id"] for a in page1["items"]] == ids[::-1][:2]
    assert page1["next_cursor"]
    page2 = client.get(
        f"/api/v1/clients/{cid}/audits",
        params={"limit": 2, "cursor": page1["next_cursor"]},
        headers=_auth(admin_token),
    ).json()
    assert [a["id"] for a in page2["items"]] == [ids[0]]
    assert page2["next_cursor"] is None
    bad = client.get(
        f"/api/v1/clients/{cid}/audits", params={"cursor": "garbage"}, headers=_auth(admin_token)
    )
    assert bad.status_code == 400


def _compare(token: str, audit_id: str) -> Any:
    return client.get(f"/api/v1/audits/{audit_id}/comparison", headers=_auth(token))


def test_comparison_splits_issues_into_new_fixed_and_unchanged(admin_token: str, cid: str) -> None:
    first = _start(admin_token, cid).json()["id"]
    _run_queued()
    assert _compare(admin_token, first).json() == {
        "previous": None, "new": [], "fixed": [], "unchanged": [],
    }

    _routes["site"] = CLEAN_SITE  # the broken link is fixed, the missing sitemap etc. too
    second = _start(admin_token, cid).json()["id"]
    _run_queued()
    fixed = _compare(admin_token, second).json()
    assert fixed["previous"]["id"] == first
    assert fixed["new"] == [] and fixed["unchanged"] == []
    assert "broken_internal_link" in {f["code"] for f in fixed["fixed"]}

    _routes["site"] = BROKEN_SITE  # and the same problems come back
    third = _start(admin_token, cid).json()["id"]
    _run_queued()
    back = _compare(admin_token, third).json()
    assert back["previous"]["id"] == second
    assert {f["code"] for f in back["new"]} == {f["code"] for f in fixed["fixed"]}
    assert back["fixed"] == [] and back["unchanged"] == []

    fourth = _start(admin_token, cid).json()["id"]
    _run_queued()
    same = _compare(admin_token, fourth).json()
    assert same["previous"]["id"] == third
    assert same["new"] == [] and same["fixed"] == []
    assert {f["code"] for f in same["unchanged"]} == {f["code"] for f in back["new"]}


def test_comparison_skips_audits_that_did_not_finish(admin_token: str, cid: str) -> None:
    first = _start(admin_token, cid).json()["id"]
    _run_queued()
    cancelled = _start(admin_token, cid).json()
    client.delete(f"/api/v1/jobs/{cancelled['job_id']}", headers=_auth(admin_token))
    _run_queued()  # the worker sees the cancelled job and stops the audit
    third = _start(admin_token, cid).json()["id"]
    _run_queued()
    assert _compare(admin_token, third).json()["previous"]["id"] == first


def test_only_a_finished_audit_can_be_compared(admin_token: str, cid: str) -> None:
    pending = _start(admin_token, cid).json()["id"]
    assert _compare(admin_token, pending).status_code == 409


def test_another_agency_cannot_compare_an_audit(
    admin_token: str, other_token: str, cid: str
) -> None:
    audit_id = _start(admin_token, cid).json()["id"]
    _run_queued()
    assert _compare(other_token, audit_id).status_code == 404


def test_another_agency_cannot_see_or_start_audits(
    admin_token: str, other_token: str, cid: str
) -> None:
    audit_id = _start(admin_token, cid).json()["id"]
    _run_queued()
    h = _auth(other_token)
    assert _start(other_token, cid).status_code == 404
    assert client.get(f"/api/v1/clients/{cid}/audits", headers=h).status_code == 404
    assert client.get(f"/api/v1/audits/{audit_id}", headers=h).status_code == 404
    assert client.get(f"/api/v1/audits/{audit_id}/findings", headers=h).status_code == 404


def test_starting_an_audit_is_recorded_in_the_audit_log(admin_token: str, cid: str) -> None:
    audit_id = _start(admin_token, cid).json()["id"]
    r = client.get("/api/v1/audit-log", params={"limit": 100}, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    entries = [e for e in r.json()["items"] if e["action"] == "audit.started"]
    assert any(e["entity_id"] == audit_id for e in entries)


def test_deleting_a_client_removes_its_audits(admin_token: str, tenant_id: UUID) -> None:
    doomed = _new_client(admin_token, name="Doomed", website_url="https://doomed.test")
    audit_id = _start(admin_token, doomed).json()["id"]
    _run_queued()

    async def _purge() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await set_rls_context(session, tenant_id=tenant_id)
            await session.execute(text("DELETE FROM clients WHERE id = :i"), {"i": doomed})
            await session.commit()

    asyncio.run(_purge())
    assert client.get(f"/api/v1/audits/{audit_id}", headers=_auth(admin_token)).status_code == 404
