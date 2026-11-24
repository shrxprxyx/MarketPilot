"""
Auto-ingest of the brand profile (FR-RAG-02). Embeddings and retrieval are real; only
the Celery hand-off is replaced, so tests run the queued ingestion explicitly.
"""
import asyncio
import json
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.ai.providers as providers
import app.api.v1.clients as clients_api
import app.api.v1.knowledge as knowledge_api
import app.db.engine as db_engine
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.main import app
from app.models.brand_profile import BrandProfile
from app.models.membership import Membership
from app.models.user import User
from app.rag.auto_docs import brand_profile_document_text
from app.rag.ingest import ingest_document

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {"email": "auto-admin@example.com", "password": "autoadmin12345", "tenant_name": "Auto Co"}
_OTHER = {
    "email": "auto-other@example.com",
    "password": "autoother12345",
    "tenant_name": "Other Auto Co",
}

PROFILE = {
    "voice": "Playful pirate captain",
    "tone": "Cheeky",
    "audience": "Coastal families",
    "keywords": ["rum", "treasure"],
    "do_rules": ["Say ahoy"],
    "dont_rules": ["Never swear"],
    "sample_text": "Arr, welcome aboard the good ship Brew.",
}
EMPTY = {k: None for k in PROFILE}

_jobs: list[tuple[UUID, UUID]] = []


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(creds: dict[str, str]) -> dict[str, Any]:
    client.post("/api/v1/auth/register", json=creds)
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _member_token(tenant_id: UUID) -> str:
    async with db_engine.AsyncSessionLocal() as session:
        user = User(
            email="auto-member@example.com", hashed_password=hash_password("x-irrelevant-1")
        )
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="member"))
        await session.commit()
        return create_access_token(user.id, tenant_id, "member")


def _run_pending_jobs() -> None:
    async def _go(tenant_id: UUID, doc_id: UUID) -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await ingest_document(session, tenant_id, doc_id)

    while _jobs:
        tenant_id, doc_id = _jobs.pop()
        asyncio.run(_go(tenant_id, doc_id))


@pytest.fixture(autouse=True)
def _capture_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    _jobs.clear()
    enqueue = lambda t, d, job_id=None: _jobs.append((t, d))  # noqa: E731
    monkeypatch.setattr(clients_api, "enqueue_ingest", enqueue)
    monkeypatch.setattr(knowledge_api, "enqueue_ingest", enqueue)


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE slug IN ('auto-co', 'other-auto-co')")
            )
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN ('auto-admin@example.com', "
                    "'auto-other@example.com', 'auto-member@example.com')"
                )
            )
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    return str(_register(_ADMIN)["access_token"])


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    return UUID(client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_id"])


def _new_client(token: str, name: str = "Auto Client") -> str:
    r = client.post(
        "/api/v1/clients",
        json={"name": name, "industry": "Coffee", "goals": ["Grow"]},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _put_profile(token: str, cid: str, body: dict[str, Any] | None = None) -> Any:
    return client.put(
        f"/api/v1/clients/{cid}/brand-profile", json=PROFILE if body is None else body,
        headers=_auth(token),
    )


def _docs(token: str, cid: str) -> list[dict[str, Any]]:
    r = client.get(f"/api/v1/clients/{cid}/documents", headers=_auth(token))
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


def _search(token: str, cid: str, query: str) -> list[dict[str, Any]]:
    r = client.post(
        f"/api/v1/clients/{cid}/search", json={"query": query}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    return list(r.json()["results"])


def _chunk_count(tenant_id: UUID, cid: str) -> int:
    async def _go() -> int:
        async with db_engine.AsyncSessionLocal() as session:
            await set_rls_context(session, tenant_id=tenant_id)
            return int(
                await session.scalar(
                    text("SELECT count(*) FROM document_chunks WHERE client_id = CAST(:c AS uuid)"),
                    {"c": cid},
                )
                or 0
            )

    return asyncio.run(_go())


# ---------- sync on save ----------


def test_saving_profile_creates_pending_auto_document_then_ready_and_searchable(
    admin_token: str,
) -> None:
    cid = _new_client(admin_token)
    assert _put_profile(admin_token, cid).status_code == 200
    docs = _docs(admin_token, cid)
    assert len(docs) == 1
    assert docs[0]["source_type"] == "brand_profile" and docs[0]["title"] == "Brand profile"
    assert docs[0]["status"] == "pending" and len(_jobs) == 1

    _run_pending_jobs()
    assert _docs(admin_token, cid)[0]["status"] == "ready"
    hits = _search(admin_token, cid, "pirate captain voice")
    assert hits and hits[0]["document_title"] == "Brand profile"
    assert "Arr, welcome aboard" in hits[0]["text"]  # the sample text is indexed too


def test_updating_profile_replaces_chunks(admin_token: str, tenant_id: UUID) -> None:
    cid = _new_client(admin_token)
    _put_profile(admin_token, cid)
    _run_pending_jobs()
    before = _chunk_count(tenant_id, cid)

    updated = _put_profile(admin_token, cid, PROFILE | {"voice": "Calm mountain monk"})
    assert updated.status_code == 200
    assert len(_jobs) == 1
    _run_pending_jobs()
    assert len(_docs(admin_token, cid)) == 1  # updated in place, not a second document
    assert _chunk_count(tenant_id, cid) == before  # replaced, not doubled
    texts = " ".join(h["text"] for h in _search(admin_token, cid, "monk pirate voice"))
    assert "Calm mountain monk" in texts and "Playful pirate captain" not in texts


def test_unchanged_profile_does_not_requeue(admin_token: str) -> None:
    cid = _new_client(admin_token)
    _put_profile(admin_token, cid)
    _run_pending_jobs()
    assert _put_profile(admin_token, cid).status_code == 200
    assert _jobs == []
    assert _docs(admin_token, cid)[0]["status"] == "ready"  # not reset to pending


def test_clearing_profile_removes_document_and_chunks(
    admin_token: str, tenant_id: UUID
) -> None:
    cid = _new_client(admin_token)
    _put_profile(admin_token, cid)
    _run_pending_jobs()
    assert _chunk_count(tenant_id, cid) > 0
    assert _put_profile(admin_token, cid, EMPTY).status_code == 200
    assert _docs(admin_token, cid) == []
    assert _chunk_count(tenant_id, cid) == 0


def test_enqueue_failure_does_not_fail_the_save(
    admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(t: UUID, d: UUID) -> None:
        raise RuntimeError("broker is down")

    monkeypatch.setattr(clients_api, "enqueue_ingest", boom)
    cid = _new_client(admin_token)
    r = _put_profile(admin_token, cid)
    assert r.status_code == 200, r.text
    assert r.json()["voice"] == PROFILE["voice"]  # the profile itself was saved
    assert _docs(admin_token, cid)[0]["status"] == "pending"  # Re-index can fix it later


def test_resaving_retries_a_document_that_never_finished_indexing(
    admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(t: UUID, d: UUID) -> None:
        raise RuntimeError("broker is down")

    cid = _new_client(admin_token)
    with monkeypatch.context() as broken:
        broken.setattr(clients_api, "enqueue_ingest", boom)
        assert _put_profile(admin_token, cid).status_code == 200
    assert _jobs == [] and _docs(admin_token, cid)[0]["status"] == "pending"

    assert _put_profile(admin_token, cid).status_code == 200  # same content, queue is back
    assert len(_jobs) == 1  # the stuck document is queued again
    _run_pending_jobs()
    assert _docs(admin_token, cid)[0]["status"] == "ready"


def test_identical_uploaded_text_does_not_collide(admin_token: str) -> None:
    cid = _new_client(admin_token)
    auto_text = brand_profile_document_text(BrandProfile(**PROFILE))
    added = client.post(
        f"/api/v1/clients/{cid}/documents",
        json={"title": "Pasted copy", "text": auto_text},
        headers=_auth(admin_token),
    )
    assert added.status_code == 202 and added.json()["duplicate"] is False
    assert _put_profile(admin_token, cid).status_code == 200
    assert {d["source_type"] for d in _docs(admin_token, cid)} == {"brand_doc", "brand_profile"}


# ---------- strategy generation is unchanged ----------


def test_strategy_excludes_profile_chunks_and_has_the_profile_once(
    admin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = client.post(
        "/api/v1/ai/connections",
        json={"provider": "openai", "label": "auto", "api_key": "sk-auto-key-1234"},
        headers=_auth(admin_token),
    )
    route = [{"task_type": "strategy", "connection_id": conn.json()["id"], "model": "gpt-4o-mini"}]
    routed = client.put("/api/v1/ai/routes", json=route, headers=_auth(admin_token))
    assert routed.status_code == 200
    seen: list[dict[str, Any]] = []
    plan = {
        "summary": "s",
        "objectives": [{"title": "o", "kpis": [{"name": "k", "target": "1"}]}],
        "channels": [{"name": "c", "rationale": "r"}],
        "risks": [{"risk": "x", "mitigation": "y"}],
    }

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        seen.append(body)
        return {
            "choices": [{"message": {"content": json.dumps(plan)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    monkeypatch.setattr(providers, "_post_json", fake_post)
    cid = _new_client(admin_token, "Strategy Auto Client")
    _put_profile(admin_token, cid)
    client.post(
        f"/api/v1/clients/{cid}/documents",
        json={"title": "Pirate rum notes", "text": "Our pirate rum is aged in oak barrels."},
        headers=_auth(admin_token),
    )
    _run_pending_jobs()

    r = client.post(
        f"/api/v1/clients/{cid}/strategies", json={"month": "2026-12"}, headers=_auth(admin_token)
    )
    assert r.status_code == 201, r.text
    titles = {s["document_title"] for s in r.json()["sources"]}
    assert titles == {"Pirate rum notes"}  # the auto profile document is not a "source"
    prompt = "\n".join(m["content"] for m in seen[-1]["messages"])
    assert prompt.count("Playful pirate captain") == 1


# ---------- guards ----------


def test_auto_document_cannot_be_deleted_but_can_be_reindexed(admin_token: str) -> None:
    cid = _new_client(admin_token)
    _put_profile(admin_token, cid)
    _run_pending_jobs()
    doc_id = _docs(admin_token, cid)[0]["id"]

    r = client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(admin_token))
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "This document is managed automatically from the Brand profile tab."
    )
    assert len(_docs(admin_token, cid)) == 1

    re = client.post(f"/api/v1/documents/{doc_id}/reindex", headers=_auth(admin_token))
    assert re.status_code == 202 and len(_jobs) == 1


def test_other_tenant_and_members_are_locked_out(admin_token: str, tenant_id: UUID) -> None:
    cid = _new_client(admin_token)
    _put_profile(admin_token, cid)
    doc_id = _docs(admin_token, cid)[0]["id"]
    other = str(_register(_OTHER)["access_token"])
    assert client.get(f"/api/v1/clients/{cid}/documents", headers=_auth(other)).status_code == 404
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(other)).status_code == 404
    member = asyncio.run(_member_token(tenant_id))
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(member)).status_code == 403
    assert _put_profile(member, cid).status_code == 403
