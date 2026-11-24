"""
Knowledge base / RAG (FR-RAG-01, 03, 04). Embeddings are real (fastembed); only
the Celery hand-off is replaced, so tests run ingestion explicitly.
"""
import asyncio
import io
from typing import Any
from uuid import UUID

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.api.v1.knowledge as knowledge_api
import app.db.engine as db_engine
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.main import app
from app.models.membership import Membership
from app.models.user import User
from app.rag.chunking import chunk_text
from app.rag.extract import ExtractionError, content_hash, extract_text
from app.rag.ingest import ingest_document
from app.rag.retrieval import rrf_fuse

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {"email": "kb-admin@example.com", "password": "kbadmin12345", "tenant_name": "Kb Co"}
_OTHER = {"email": "kb-other@example.com", "password": "kbother12345", "tenant_name": "Other Kb Co"}

COFFEE = (
    "Our espresso blends are roasted in small batches and shipped within two days. "
    "Subscribers get fresh whole bean coffee every week with free delivery."
)
LEGAL = (
    "The tenancy agreement requires landlords to protect deposits in a government approved "
    "scheme within thirty days and to provide prescribed information to tenants."
)

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
        user = User(email="kb-member@example.com", hashed_password=hash_password("x-irrelevant-1"))
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
    monkeypatch.setattr(
        knowledge_api, "enqueue_ingest", lambda t, d, job_id=None: _jobs.append((t, d))
    )


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE slug IN ('kb-co', 'other-kb-co')")
            )
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN ('kb-admin@example.com', "
                    "'kb-other@example.com', 'kb-member@example.com')"
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


@pytest.fixture(scope="module")
def client_id(admin_token: str) -> str:
    r = client.post("/api/v1/clients", json={"name": "KB Client"}, headers=_auth(admin_token))
    return str(r.json()["id"])


def _add_text(token: str, cid: str, title: str, body: str, **extra: Any) -> Any:
    return client.post(
        f"/api/v1/clients/{cid}/documents",
        json={"title": title, "text": body} | extra,
        headers=_auth(token),
    )


def _search(token: str, cid: str, query: str, **extra: Any) -> Any:
    return client.post(
        f"/api/v1/clients/{cid}/search", json={"query": query} | extra, headers=_auth(token)
    )


# ---------- pure units ----------


def test_chunking_packs_paragraphs_and_overlaps() -> None:
    paragraphs = [f"Paragraph {i}. " + "word " * 120 for i in range(10)]
    chunks = chunk_text("\n\n".join(paragraphs), chunk_chars=1000, overlap_chars=100)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    # overlap: the start of each chunk repeats the end of the previous one
    tail = chunks[0][-60:].split(" ", 1)[1]
    assert tail in chunks[1]


def test_chunking_splits_oversized_paragraph_and_handles_empty() -> None:
    assert chunk_text("   \n\n  ") == []
    chunks = chunk_text("x" * 5000, chunk_chars=1000, overlap_chars=100)
    assert all(len(c) <= 1000 for c in chunks) and len(chunks) >= 5


def test_rrf_prefers_items_ranked_by_both_lists() -> None:
    a, b, c = (UUID(int=i) for i in (1, 2, 3))
    fused = rrf_fuse([[a, b], [c, b]])
    assert fused[0][0] == b


def test_extraction_formats_and_limits() -> None:
    buf = io.BytesIO()
    d = DocxDocument()
    d.add_paragraph("Docx paragraph one")
    d.save(buf)
    assert "Docx paragraph one" in extract_text("a.docx", buf.getvalue())
    cleaned = extract_text("a.md", b"# Title\n\nbody\x00")  # control char stripped
    assert cleaned == "# Title\n\nbody"
    with pytest.raises(ExtractionError):
        extract_text("a.exe", b"MZ")
    with pytest.raises(ExtractionError):
        extract_text("a.pdf", b"not a pdf")
    with pytest.raises(ExtractionError):
        extract_text("a.txt", b"\xff\xfe\x00bad")
    with pytest.raises(ExtractionError):
        extract_text("a.txt", b"x" * (10 * 1024 * 1024 + 1))


def test_content_hash_ignores_whitespace_and_case() -> None:
    assert content_hash("Hello   World") == content_hash("hello world\n")


# ---------- API ----------


def test_add_text_document_then_ingest_then_search(admin_token: str, client_id: str) -> None:
    r = _add_text(admin_token, client_id, "Coffee page", COFFEE)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending" and r.json()["duplicate"] is False
    assert len(_jobs) == 1
    _add_text(admin_token, client_id, "Tenancy guide", LEGAL, source_type="past_content")
    _run_pending_jobs()

    docs = client.get(f"/api/v1/clients/{client_id}/documents", headers=_auth(admin_token)).json()
    assert {d["status"] for d in docs["items"]} == {"ready"}

    hits = _search(admin_token, client_id, "fresh roasted coffee beans").json()["results"]
    assert hits and hits[0]["document_title"] == "Coffee page"

    legal = _search(admin_token, client_id, "deposit protection for tenants").json()["results"]
    assert legal[0]["document_title"] == "Tenancy guide"

    only_past = _search(
        admin_token, client_id, "coffee", source_type="past_content"
    ).json()["results"]
    assert {h["source_type"] for h in only_past} == {"past_content"}


def test_duplicate_content_is_skipped(admin_token: str, client_id: str) -> None:
    first = _add_text(admin_token, client_id, "Dup A", "Unique duplicate text body here.")
    second = _add_text(admin_token, client_id, "Dup B", "unique  duplicate TEXT body here.\n")
    assert second.status_code == 202
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]
    assert len(_jobs) == 1  # no second indexing job


def test_file_upload_docx(admin_token: str, client_id: str) -> None:
    buf = io.BytesIO()
    d = DocxDocument()
    d.add_paragraph("Quarterly brand voice guidelines: friendly, concise and confident.")
    d.save(buf)
    r = client.post(
        f"/api/v1/clients/{client_id}/documents",
        files={"file": ("voice.docx", buf.getvalue(), "application/octet-stream")},
        data={"title": "Voice guide"},
        headers=_auth(admin_token),
    )
    assert r.status_code == 202, r.text
    assert r.json()["source_type"] == "upload" and r.json()["title"] == "Voice guide"


def test_upload_validation(admin_token: str, client_id: str) -> None:
    bad_type = client.post(
        f"/api/v1/clients/{client_id}/documents",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        headers=_auth(admin_token),
    )
    assert bad_type.status_code == 422
    assert _add_text(admin_token, client_id, "", "x").status_code == 422
    assert _add_text(admin_token, client_id, "t", "x", source_type="audit").status_code == 422
    no_file = client.post(
        f"/api/v1/clients/{client_id}/documents", files={"other": ("a.txt", b"x")},
        headers=_auth(admin_token),
    )
    assert no_file.status_code == 422


def test_delete_removes_chunks(admin_token: str, client_id: str, tenant_id: UUID) -> None:
    doc = _add_text(admin_token, client_id, "Temp", "Zebra crossing safety instructions.").json()
    _run_pending_jobs()
    before = _search(admin_token, client_id, "zebra crossing").json()["results"]
    assert before[0]["document_id"] == doc["id"]

    r = client.delete(f"/api/v1/documents/{doc['id']}", headers=_auth(admin_token))
    assert r.status_code == 204
    after = _search(admin_token, client_id, "zebra crossing").json()["results"]
    assert all(h["document_id"] != doc["id"] for h in after)

    async def _count() -> int:
        async with db_engine.AsyncSessionLocal() as session:
            await set_rls_context(session, tenant_id=tenant_id)
            res = await session.execute(
                text("SELECT count(*) FROM document_chunks WHERE document_id = CAST(:d AS uuid)"),
                {"d": doc["id"]},
            )
            return int(res.scalar_one())

    assert asyncio.run(_count()) == 0


def test_reindex_rebuilds_chunks_without_duplicating(
    admin_token: str, client_id: str, tenant_id: UUID
) -> None:
    doc = _add_text(admin_token, client_id, "Reindex me", "Quokkas are small marsupials.").json()
    _run_pending_jobs()
    r = client.post(f"/api/v1/documents/{doc['id']}/reindex", headers=_auth(admin_token))
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert len(_jobs) == 1
    _run_pending_jobs()
    hits = _search(admin_token, client_id, "quokkas").json()["results"]
    assert len([h for h in hits if h["document_id"] == doc["id"]]) == 1


def test_unready_documents_are_not_searchable(admin_token: str, client_id: str) -> None:
    doc = _add_text(admin_token, client_id, "Pending", "Aardvark burrow engineering notes.").json()
    pending = _search(admin_token, client_id, "aardvark burrow").json()["results"]
    assert all(h["document_id"] != doc["id"] for h in pending)
    _run_pending_jobs()
    ready = _search(admin_token, client_id, "aardvark burrow").json()["results"]
    assert ready[0]["document_id"] == doc["id"]


def test_rbac_member_reads_but_cannot_write(
    admin_token: str, client_id: str, tenant_id: UUID
) -> None:
    member = asyncio.run(_member_token(tenant_id))
    assert _add_text(member, client_id, "Nope", "blocked").status_code == 403
    listing = client.get(f"/api/v1/clients/{client_id}/documents", headers=_auth(member))
    assert listing.status_code == 200
    assert _search(member, client_id, "coffee").status_code == 200
    doc = _add_text(admin_token, client_id, "Member cannot delete", "Some other text 123.").json()
    delete = client.delete(f"/api/v1/documents/{doc['id']}", headers=_auth(member))
    reindex = client.post(f"/api/v1/documents/{doc['id']}/reindex", headers=_auth(member))
    assert delete.status_code == 403 and reindex.status_code == 403


def test_cross_tenant_isolation(admin_token: str, client_id: str) -> None:
    other = str(_register(_OTHER)["access_token"])
    other_client = client.post("/api/v1/clients", json={"name": "Theirs"}, headers=_auth(other))
    other_cid = str(other_client.json()["id"])

    # other tenant cannot touch this tenant's client
    assert _add_text(other, client_id, "x", "y").status_code == 404
    assert _search(other, client_id, "coffee").status_code == 404
    listing = client.get(f"/api/v1/clients/{client_id}/documents", headers=_auth(other))
    assert listing.status_code == 404

    # their own client's index is empty even though identical content exists elsewhere
    _add_text(other, other_cid, "Their coffee", COFFEE)
    _run_pending_jobs()
    mine = _search(admin_token, client_id, "espresso blends roasted").json()["results"]
    theirs = _search(other, other_cid, "espresso blends roasted").json()["results"]
    assert {h["document_title"] for h in mine}.isdisjoint({h["document_title"] for h in theirs})

    doc = _add_text(admin_token, client_id, "Mine only", "Private marmalade recipe notes.").json()
    assert client.delete(f"/api/v1/documents/{doc['id']}", headers=_auth(other)).status_code == 404
