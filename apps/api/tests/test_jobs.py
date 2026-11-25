"""Background jobs (SRS §3.5, §8): indexing creates a job row that tracks progress, retries
and cancellation; `Idempotency-Key` makes retried POSTs safe; progress streams over SSE using
a single-use ticket. The worker's task body is called directly (no broker), the database,
Redis and the API are real."""
import asyncio
import json
import threading
import time
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.api.v1.knowledge as knowledge_api
import app.db.engine as db_engine
import app.rag.ingest as ingest_mod
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.jobs.progress import update_job
from app.main import app
from app.models.membership import Membership
from app.models.user import User
from app.rag.ingest import ingest_document

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {"email": "jobs-admin@example.com", "password": "jobsadmin1234", "tenant_name": "Jobs Co"}
_OTHER = {
    "email": "jobs-other@example.com",
    "password": "jobsother1234",
    "tenant_name": "Other Jobs Co",
}
_queued: list[tuple[UUID, UUID, UUID | None]] = []


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(creds: dict[str, str]) -> str:
    client.post("/api/v1/auth/register", json=creds)
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE slug IN ('jobs-co', 'other-jobs-co')")
            )
            await session.execute(text("DELETE FROM users WHERE email LIKE 'jobs-%@example.com'"))
            await session.commit()

    asyncio.run(_delete())
    yield
    asyncio.run(_delete())


@pytest.fixture(autouse=True)
def _capture_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    _queued.clear()
    monkeypatch.setattr(
        knowledge_api,
        "enqueue_ingest",
        lambda t, d, job_id=None: _queued.append((t, d, job_id)),
    )


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _register(_ADMIN)


@pytest.fixture(scope="module")
def other_token() -> str:
    return _register(_OTHER)


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    return UUID(client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_id"])


@pytest.fixture(scope="module")
def client_id(admin_token: str) -> str:
    r = client.post("/api/v1/clients", json={"name": "Jobs Client"}, headers=_auth(admin_token))
    return str(r.json()["id"])


def _token_for_role(tenant_id: UUID, role: str) -> str:
    async def _go() -> str:
        async with db_engine.AsyncSessionLocal() as session:
            user = User(
                email=f"jobs-{role}@example.com", hashed_password=hash_password("irrelevant-1234")
            )
            session.add(user)
            await session.flush()
            await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
            session.add(Membership(user_id=user.id, tenant_id=tenant_id, role=role))
            await session.commit()
            return create_access_token(user.id, tenant_id, role)

    return asyncio.run(_go())


def _add_doc(
    token: str, cid: str, body: str, key: str | None = None, title: str = "Doc"
) -> dict[str, Any]:
    headers = _auth(token) | ({"Idempotency-Key": key} if key else {})
    r = client.post(
        f"/api/v1/clients/{cid}/documents", json={"title": title, "text": body}, headers=headers
    )
    assert r.status_code == 202, r.text
    return dict(r.json())


def _run_worker(tenant_id: UUID, doc_id: UUID, job_id: UUID, **kw: Any) -> bool:
    async def _go() -> bool:
        async with db_engine.AsyncSessionLocal() as session:
            return await ingest_document(session, tenant_id, doc_id, job_id, **kw)

    return asyncio.run(_go())


def _job(token: str, job_id: str) -> dict[str, Any]:
    r = client.get(f"/api/v1/jobs/{job_id}", headers=_auth(token))
    assert r.status_code == 200, r.text
    return dict(r.json())


# ---------- indexing as a job ----------


def test_upload_returns_a_queued_job_and_the_worker_completes_it(
    admin_token: str, tenant_id: UUID, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Roasted in small batches. " * 30, title="Beans")
    job_id = out["job_id"]
    assert _job(admin_token, job_id)["status"] == "queued"
    assert _queued == [(tenant_id, UUID(out["id"]), UUID(job_id))]

    assert _run_worker(tenant_id, UUID(out["id"]), UUID(job_id)) is True

    done = _job(admin_token, job_id)
    assert (done["status"], done["progress"], done["type"]) == ("succeeded", 100, "document.index")
    assert done["result_ref"]["document_id"] == out["id"]
    assert done["result_ref"]["chunks"] >= 1
    docs = client.get(f"/api/v1/clients/{client_id}/documents", headers=_auth(admin_token))
    assert next(d for d in docs.json()["items"] if d["id"] == out["id"])["status"] == "ready"


def test_a_failure_retries_then_fails_for_good(
    admin_token: str, tenant_id: UUID, client_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _add_doc(admin_token, client_id, "A document that cannot be embedded.", title="Bad")
    doc, job = UUID(out["id"]), UUID(out["job_id"])

    async def boom(texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(ingest_mod, "embed_documents", boom)

    assert _run_worker(tenant_id, doc, job, will_retry=True) is False  # first attempt
    assert _job(admin_token, str(job))["status"] == "queued"  # waiting for the retry
    assert "Retrying" in _job(admin_token, str(job))["message"]

    assert _run_worker(tenant_id, doc, job, will_retry=False) is False  # last attempt
    failed = _job(admin_token, str(job))
    assert failed["status"] == "failed" and failed["error"]
    docs = client.get(f"/api/v1/clients/{client_id}/documents", headers=_auth(admin_token))
    assert next(d for d in docs.json()["items"] if d["id"] == str(doc))["status"] == "failed"


def test_reindex_creates_a_new_job(admin_token: str, tenant_id: UUID, client_id: str) -> None:
    out = _add_doc(admin_token, client_id, "Reindex me please. " * 20, title="Re")
    _run_worker(tenant_id, UUID(out["id"]), UUID(out["job_id"]))
    r = client.post(f"/api/v1/documents/{out['id']}/reindex", headers=_auth(admin_token))
    assert r.status_code == 202, r.text
    assert r.json()["job_id"] not in (None, out["job_id"])
    assert r.json()["status"] == "pending"


# ---------- Idempotency-Key ----------


def test_same_idempotency_key_replays_the_original(
    admin_token: str, client_id: str
) -> None:
    first = _add_doc(admin_token, client_id, "Idempotent content one.", key="key-aaaa-0001")
    second = _add_doc(admin_token, client_id, "Idempotent content one.", key="key-aaaa-0001")
    assert second["id"] == first["id"] and second["job_id"] == first["job_id"]
    assert len([q for q in _queued if q[1] == UUID(first["id"])]) == 1  # queued exactly once


def test_reusing_a_key_for_a_different_request_is_refused(
    admin_token: str, client_id: str
) -> None:
    _add_doc(admin_token, client_id, "Original request body.", key="key-bbbb-0002")
    r = client.post(
        f"/api/v1/clients/{client_id}/documents",
        json={"title": "Doc", "text": "A different body."},
        headers=_auth(admin_token) | {"Idempotency-Key": "key-bbbb-0002"},
    )
    assert r.status_code == 422
    assert "Idempotency-Key" in r.json()["detail"]


@pytest.mark.parametrize("key", ["short", "has spaces in it!!", "x" * 101])
def test_malformed_idempotency_keys_are_rejected(
    admin_token: str, client_id: str, key: str
) -> None:
    r = client.post(
        f"/api/v1/clients/{client_id}/documents",
        json={"title": "Doc", "text": "Some text."},
        headers=_auth(admin_token) | {"Idempotency-Key": key},
    )
    assert r.status_code == 422


def test_reindex_replays_with_the_same_key(admin_token: str, client_id: str) -> None:
    out = _add_doc(admin_token, client_id, "Replay reindex body.", title="Rx")
    hdr = _auth(admin_token) | {"Idempotency-Key": "key-cccc-0003"}
    a = client.post(f"/api/v1/documents/{out['id']}/reindex", headers=hdr).json()
    b = client.post(f"/api/v1/documents/{out['id']}/reindex", headers=hdr).json()
    assert a["job_id"] == b["job_id"]


# ---------- reading, listing, cancelling ----------


def test_cancel_a_queued_job_and_the_worker_respects_it(
    admin_token: str, tenant_id: UUID, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Cancel this indexing run.", title="Cx")
    r = client.delete(f"/api/v1/jobs/{out['job_id']}", headers=_auth(admin_token))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"

    assert _run_worker(tenant_id, UUID(out["id"]), UUID(out["job_id"])) is True
    assert _job(admin_token, out["job_id"])["status"] == "cancelled"  # not revived by the worker
    docs = client.get(f"/api/v1/clients/{client_id}/documents", headers=_auth(admin_token))
    doc = next(d for d in docs.json()["items"] if d["id"] == out["id"])
    assert doc["status"] == "failed" and "cancelled" in doc["error"]


def test_cancelling_a_reindex_keeps_the_document_ready_and_searchable(
    admin_token: str, tenant_id: UUID, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Zanzibar clove harvest notes.", title="Reindex Cx")
    assert _run_worker(tenant_id, UUID(out["id"]), UUID(out["job_id"])) is True

    again = client.post(f"/api/v1/documents/{out['id']}/reindex", headers=_auth(admin_token))
    assert again.status_code == 202
    job_id = again.json()["job_id"]
    client.delete(f"/api/v1/jobs/{job_id}", headers=_auth(admin_token))
    assert _run_worker(tenant_id, UUID(out["id"]), UUID(job_id)) is True

    docs = client.get(f"/api/v1/clients/{client_id}/documents", headers=_auth(admin_token))
    doc = next(d for d in docs.json()["items"] if d["id"] == out["id"])
    assert doc["status"] == "ready" and doc["error"] is None
    hits = client.post(
        f"/api/v1/clients/{client_id}/search",
        json={"query": "Zanzibar clove harvest"},
        headers=_auth(admin_token),
    ).json()["results"]
    assert any(h["document_id"] == out["id"] for h in hits)


def test_cancelling_a_finished_job_conflicts(
    admin_token: str, tenant_id: UUID, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Finish then cancel. " * 10, title="Fc")
    _run_worker(tenant_id, UUID(out["id"]), UUID(out["job_id"]))
    r = client.delete(f"/api/v1/jobs/{out['job_id']}", headers=_auth(admin_token))
    assert r.status_code == 409


def test_cancel_is_audited_and_needs_manager_or_admin(
    admin_token: str, tenant_id: UUID, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Audit the cancel.", title="Au")
    member = _token_for_role(tenant_id, "member")
    assert client.delete(f"/api/v1/jobs/{out['job_id']}", headers=_auth(member)).status_code == 403
    assert client.get(f"/api/v1/jobs/{out['job_id']}", headers=_auth(member)).status_code == 200
    client.delete(f"/api/v1/jobs/{out['job_id']}", headers=_auth(admin_token))
    entries = client.get(
        "/api/v1/audit-log", params={"limit": 100}, headers=_auth(admin_token)
    ).json()["items"]
    assert any(
        e["action"] == "job.cancelled" and e["meta"] == {"type": "document.index"} for e in entries
    )


def test_list_jobs_filters_and_paginates(admin_token: str, client_id: str) -> None:
    for i in range(3):
        _add_doc(admin_token, client_id, f"Listing body number {i}.", title=f"L{i}")
    page = client.get("/api/v1/jobs", params={"limit": 2}, headers=_auth(admin_token)).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    nxt = client.get(
        "/api/v1/jobs",
        params={"limit": 2, "cursor": page["next_cursor"]},
        headers=_auth(admin_token),
    ).json()
    assert {j["job_id"] for j in nxt["items"]}.isdisjoint({j["job_id"] for j in page["items"]})
    only = client.get(
        "/api/v1/jobs", params={"type": "nope"}, headers=_auth(admin_token)
    ).json()
    assert only["items"] == []
    bad = client.get("/api/v1/jobs", params={"cursor": "garbage"}, headers=_auth(admin_token))
    assert bad.status_code == 400


def test_other_tenants_cannot_see_or_cancel_a_job(
    admin_token: str, other_token: str, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Private to the first tenant.", title="Pv")
    peek = client.get(f"/api/v1/jobs/{out['job_id']}", headers=_auth(other_token))
    assert peek.status_code == 404
    assert (
        client.delete(f"/api/v1/jobs/{out['job_id']}", headers=_auth(other_token)).status_code
        == 404
    )
    listing = client.get("/api/v1/jobs", headers=_auth(other_token)).json()["items"]
    ids = [j["job_id"] for j in listing]
    assert out["job_id"] not in ids


def test_jobs_require_authentication() -> None:
    assert client.get("/api/v1/jobs").status_code == 401


def test_a_broken_queue_fails_the_job_but_keeps_the_upload(
    admin_token: str, client_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(t: UUID, d: UUID, job_id: UUID | None = None) -> None:
        raise RuntimeError("broker is down")

    monkeypatch.setattr(knowledge_api, "enqueue_ingest", broken)
    out = _add_doc(admin_token, client_id, "Saved even if the queue is down.", title="Bq")
    job = _job(admin_token, out["job_id"])
    assert job["status"] == "failed" and "queue" in job["error"]
    assert out["status"] == "pending"  # Re-index can fix it later


# ---------- stream tickets and SSE ----------


def test_stream_ticket_is_single_use(admin_token: str, client_id: str) -> None:
    out = _add_doc(admin_token, client_id, "Ticket test document.", title="Tk")
    t = client.post("/api/v1/auth/stream-ticket", headers=_auth(admin_token))
    assert t.status_code == 200 and t.json()["expires_in"] == 60
    ticket = t.json()["ticket"]
    # a queued job would stream forever; cancel it so the stream ends after its snapshot
    client.delete(f"/api/v1/jobs/{out['job_id']}", headers=_auth(admin_token))

    first = client.get(f"/api/v1/jobs/{out['job_id']}/events", params={"ticket": ticket})
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert '"status": "cancelled"' in first.text

    again = client.get(f"/api/v1/jobs/{out['job_id']}/events", params={"ticket": ticket})
    assert again.status_code == 401  # already redeemed


def test_stream_ticket_requires_login_and_events_reject_junk() -> None:
    assert client.post("/api/v1/auth/stream-ticket").status_code == 401
    r = client.get(f"/api/v1/jobs/{UUID(int=1)}/events", params={"ticket": "nope"})
    assert r.status_code == 401
    assert client.get(f"/api/v1/jobs/{UUID(int=1)}/events").status_code == 401


def test_a_ticket_only_opens_streams_for_its_own_tenant(
    admin_token: str, other_token: str, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Cross tenant stream.", title="Xs")
    ticket = client.post("/api/v1/auth/stream-ticket", headers=_auth(other_token)).json()["ticket"]
    r = client.get(f"/api/v1/jobs/{out['job_id']}/events", params={"ticket": ticket})
    assert r.status_code == 404


def test_bearer_token_also_works_for_the_stream(admin_token: str, client_id: str) -> None:
    out = _add_doc(admin_token, client_id, "Bearer stream document.", title="Bs")
    client.delete(f"/api/v1/jobs/{out['job_id']}", headers=_auth(admin_token))
    r = client.get(f"/api/v1/jobs/{out['job_id']}/events", headers=_auth(admin_token))
    assert r.status_code == 200 and '"status": "cancelled"' in r.text


def test_progress_streams_live_until_the_job_finishes(
    admin_token: str, tenant_id: UUID, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Stream me live.", title="Lv")
    job_id = UUID(out["job_id"])
    ticket = client.post("/api/v1/auth/stream-ticket", headers=_auth(admin_token)).json()["ticket"]

    def worker() -> None:
        time.sleep(1.0)  # let the stream attach first

        async def go() -> None:
            async with db_engine.AsyncSessionLocal() as s:
                await update_job(s, tenant_id, job_id, status="running", progress=40)
            async with db_engine.AsyncSessionLocal() as s:
                await update_job(s, tenant_id, job_id, status="succeeded", message="Indexed")

        asyncio.run(go())

    thread = threading.Thread(target=worker)
    thread.start()
    events: list[dict[str, Any]] = []
    with client.stream(
        "GET", f"/api/v1/jobs/{job_id}/events", params={"ticket": ticket}
    ) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    thread.join()

    assert [e["status"] for e in events][0] == "queued"  # the snapshot on connect
    assert [e["status"] for e in events][-1] == "succeeded"
    assert any(e["status"] == "running" and e["progress"] == 40 for e in events)


# ---------- the document list points at the job to follow ----------


def _listed(token: str, cid: str, doc_id: str) -> dict[str, Any]:
    r = client.get(
        f"/api/v1/clients/{cid}/documents", params={"limit": 100}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    return dict(next(d for d in r.json()["items"] if d["id"] == doc_id))


def test_list_exposes_the_active_job_and_drops_it_when_finished(
    admin_token: str, tenant_id: UUID, client_id: str
) -> None:
    out = _add_doc(admin_token, client_id, "Follow me from the list. " * 10, title="Ls")
    assert _listed(admin_token, client_id, out["id"])["job_id"] == out["job_id"]

    _run_worker(tenant_id, UUID(out["id"]), UUID(out["job_id"]))
    assert _listed(admin_token, client_id, out["id"])["job_id"] is None


def test_list_shows_the_newest_active_job(admin_token: str, client_id: str) -> None:
    out = _add_doc(admin_token, client_id, "Two jobs for one document.", title="Nw")
    again = client.post(
        f"/api/v1/documents/{out['id']}/reindex", headers=_auth(admin_token)
    ).json()
    assert again["job_id"] != out["job_id"]
    assert _listed(admin_token, client_id, out["id"])["job_id"] == again["job_id"]
