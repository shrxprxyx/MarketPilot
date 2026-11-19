"""Knowledge base endpoints (FR-RAG-01, 03, 04). Admins and managers manage
documents (§2.2); every role can list and search them."""
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.pagination import decode_cursor, encode_cursor
from app.core.request import client_ip
from app.db.session import get_db
from app.models.client import Client
from app.models.document import Document
from app.rag.extract import (
    MAX_UPLOAD_BYTES,
    ExtractionError,
    clean_text,
    content_hash,
    extract_text,
)
from app.rag.queue import enqueue_ingest
from app.rag.retrieval import search_chunks

router = APIRouter(tags=["knowledge"])

DB = Annotated[AsyncSession, Depends(get_db)]
WRITER = require_role("admin", "manager")
SourceType = Literal["upload", "brand_doc", "past_content"]


class TextDocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=MAX_UPLOAD_BYTES)
    source_type: SourceType = "brand_doc"


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    source_type: str
    title: str
    status: str
    error: str | None


class UploadOut(DocumentOut):
    duplicate: bool = False


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    next_cursor: str | None


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=8, ge=1, le=20)
    source_type: str | None = None


class SearchHit(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    source_type: str
    chunk_index: int
    text: str
    score: float


class SearchOut(BaseModel):
    results: list[SearchHit]


async def _client_or_404(db: AsyncSession, current: CurrentUser, client_id: UUID) -> Client:
    client = await db.scalar(
        select(Client).where(Client.id == client_id, Client.tenant_id == current.tenant_id)
    )
    if not client:
        raise ProblemException(404, "Not Found", "Client not found.")
    return client


async def _document_or_404(db: AsyncSession, current: CurrentUser, document_id: UUID) -> Document:
    doc = await db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == current.tenant_id)
    )
    if not doc:
        raise ProblemException(404, "Not Found", "Document not found.")
    return doc


async def _read_input(request: Request) -> tuple[str, str, str]:
    """Returns (title, text, source_type) from either a multipart upload or JSON text."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        upload: Any = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ProblemException(422, "Unprocessable Entity", "A 'file' field is required.")
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        try:
            text = extract_text(upload.filename or "", data)
        except ExtractionError as exc:
            raise ProblemException(422, "Unprocessable Entity", str(exc)) from exc
        title = str(form.get("title") or upload.filename or "Untitled")[:300]
        return title, text, "upload"
    try:
        body = TextDocumentIn.model_validate(await request.json())
    except (ValidationError, ValueError) as exc:
        raise ProblemException(422, "Unprocessable Entity", "Invalid document body.") from exc
    text = clean_text(body.text)
    if not text:
        raise ProblemException(422, "Unprocessable Entity", "Text is empty.")
    return body.title, text, body.source_type


@router.post("/clients/{client_id}/documents", response_model=UploadOut, status_code=202)
async def add_document(
    client_id: UUID, request: Request, current: Annotated[CurrentUser, WRITER], db: DB
) -> UploadOut:
    """Upload a file (multipart `file`) or paste text (JSON). Indexing runs in the worker."""
    await _client_or_404(db, current, client_id)
    title, text, source_type = await _read_input(request)

    digest = content_hash(text)
    existing = await db.scalar(
        select(Document).where(Document.client_id == client_id, Document.content_hash == digest)
    )
    if existing:  # FR-RAG-04: duplicate content is skipped
        return UploadOut.model_validate(existing).model_copy(update={"duplicate": True})

    doc = Document(
        tenant_id=current.tenant_id,
        client_id=client_id,
        source_type=source_type,
        title=title,
        content=text,
        content_hash=digest,
    )
    db.add(doc)
    try:
        await db.flush()
    except IntegrityError:  # lost a race with an identical upload
        await db.rollback()
        raise ProblemException(409, "Conflict", "This content was just added.") from None
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="document.created",
        entity="document",
        entity_id=doc.id,
        meta={"title": title, "source_type": source_type, "client_id": str(client_id)},
        ip=client_ip(request),
    )
    await db.commit()
    enqueue_ingest(current.tenant_id, doc.id)
    return UploadOut.model_validate(doc)


@router.get("/clients/{client_id}/documents", response_model=DocumentListOut)
async def list_documents(
    client_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> DocumentListOut:
    await _client_or_404(db, current, client_id)
    stmt = (
        select(Document)
        .where(Document.client_id == client_id, Document.tenant_id == current.tenant_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        try:
            created_at, row_id = decode_cursor(cursor)
        except ValueError as exc:
            raise ProblemException(400, "Bad Request", "Invalid cursor.") from exc
        stmt = stmt.where(tuple_(Document.created_at, Document.id) < (created_at, row_id))
    rows = list((await db.execute(stmt)).scalars().all())
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if len(rows) > limit and items else None
    )
    return DocumentListOut(
        items=[DocumentOut.model_validate(d) for d in items], next_cursor=next_cursor
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID, request: Request, current: Annotated[CurrentUser, WRITER], db: DB
) -> None:
    """Chunks go with the document (FK cascade)."""
    doc = await _document_or_404(db, current, document_id)
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="document.deleted",
        entity="document",
        entity_id=doc.id,
        meta={"title": doc.title, "client_id": str(doc.client_id)},
        ip=client_ip(request),
    )
    await db.delete(doc)
    await db.commit()


@router.post("/documents/{document_id}/reindex", response_model=DocumentOut, status_code=202)
async def reindex_document(
    document_id: UUID, current: Annotated[CurrentUser, WRITER], db: DB
) -> Document:
    doc = await _document_or_404(db, current, document_id)
    doc.status, doc.error = "pending", None
    await db.commit()
    enqueue_ingest(current.tenant_id, doc.id)
    return doc


@router.post("/clients/{client_id}/search", response_model=SearchOut)
async def search(
    client_id: UUID,
    body: SearchIn,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
) -> SearchOut:
    await _client_or_404(db, current, client_id)
    hits = await search_chunks(
        db,
        tenant_id=current.tenant_id,
        client_id=client_id,
        query=body.query,
        k=body.k,
        source_type=body.source_type,
    )
    return SearchOut(results=[SearchHit(**vars(h)) for h in hits])
