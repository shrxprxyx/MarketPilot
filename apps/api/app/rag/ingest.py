"""Background ingestion: chunk -> embed -> store (FR-RAG-01, FR-RAG-04), reporting progress to
its job row so the UI can follow it over SSE (SRS §3.5)."""
import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.rls import set_rls_context
from app.jobs.progress import is_cancelled, job_status, update_job
from app.models.document import Document, DocumentChunk
from app.rag.chunking import chunk_text
from app.rag.embeddings import embed_documents

logger = logging.getLogger(__name__)
EMBED_BATCH = 32
CANCELLED_MESSAGE = "Indexing was cancelled. Re-index to try again."


class _Cancelled(Exception):
    pass


async def ingest_document(
    db: AsyncSession,
    tenant_id: UUID,
    document_id: UUID,
    job_id: UUID | None = None,
    *,
    will_retry: bool = False,
) -> bool:
    """Idempotent: replaces any existing chunks, so it doubles as the re-index action.

    Returns True when the work is settled (indexed, cancelled, or the document is gone) and
    False when it failed. With `will_retry` a failure puts the document and job back in the
    queue instead of marking them failed, because the caller is about to run it again.
    """
    await set_rls_context(db, tenant_id=tenant_id)
    doc = await db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if doc is None:
        if job_id:
            await update_job(
                db, tenant_id, job_id, status="cancelled",
                message="The document was deleted before it was indexed.",
            )
        return True  # deleted before the job ran

    if job_id:
        state = await job_status(db, tenant_id, job_id)
        if state == "succeeded":  # a duplicate delivery of finished work
            return True
        if state == "cancelled":
            await _settle_cancelled(db, tenant_id, document_id)
            return True
        await update_job(
            db, tenant_id, job_id, status="running", progress=5, message="Reading the document"
        )
        await set_rls_context(db, tenant_id=tenant_id)
        doc = await db.scalar(select(Document).where(Document.id == document_id))
        if doc is None:
            return True

    doc.status, doc.error = "processing", None
    await db.commit()

    try:
        await set_rls_context(db, tenant_id=tenant_id)  # commit ended the transaction
        chunks = chunk_text(doc.content)
        total = max(len(chunks), 1)
        if job_id:
            await update_job(
                db, tenant_id, job_id, progress=15, message=f"Embedding {len(chunks)} passages"
            )
        vectors: list[list[float]] = []
        for i in range(0, len(chunks), EMBED_BATCH):
            if job_id and await is_cancelled(db, tenant_id, job_id):
                raise _Cancelled
            vectors.extend(await embed_documents(chunks[i : i + EMBED_BATCH]))
            if job_id:
                done = min(i + EMBED_BATCH, total)
                await update_job(db, tenant_id, job_id, progress=15 + int(75 * done / total))
        await set_rls_context(db, tenant_id=tenant_id)
        doc = await db.scalar(select(Document).where(Document.id == document_id))
        if doc is None:  # deleted while it was being embedded
            return True
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        db.add_all(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=doc.id,
                client_id=doc.client_id,
                chunk_index=i,
                text=text,
                embedding=vec,
            )
            for i, (text, vec) in enumerate(zip(chunks, vectors, strict=True))
        )
        doc.status = "ready"
        await db.commit()
        if job_id:
            await update_job(
                db, tenant_id, job_id, status="succeeded", message="Indexed",
                result_ref={"document_id": str(document_id), "chunks": len(chunks)},
            )
        return True
    except _Cancelled:
        await db.rollback()
        await _settle_cancelled(db, tenant_id, document_id)
        return True
    except Exception:
        logger.exception("Document ingestion failed", extra={"document_id": str(document_id)})
        await db.rollback()
        if will_retry:
            await _set_document(db, tenant_id, document_id, "pending", None)
            if job_id:
                await update_job(
                    db, tenant_id, job_id, status="queued", message="Indexing failed. Retrying."
                )
        else:
            await _mark_failed(db, tenant_id, document_id, "Indexing failed. Try re-indexing.")
            if job_id:
                await update_job(
                    db, tenant_id, job_id, status="failed", error="Indexing failed.",
                    message="Indexing failed",
                )
        return False


async def _set_document(
    db: AsyncSession, tenant_id: UUID, document_id: UUID, status: str, error: str | None
) -> None:
    await set_rls_context(db, tenant_id=tenant_id)
    found = await db.get(Document, document_id)
    if found:
        found.status, found.error = status, error
        await db.commit()


async def _settle_cancelled(db: AsyncSession, tenant_id: UUID, document_id: UUID) -> None:
    """A cancelled run leaves the document as it was: a re-index that was cancelled keeps its
    earlier chunks, so it stays ready and searchable. Only a document that was never indexed
    is marked failed, so the user knows to re-index it."""
    await set_rls_context(db, tenant_id=tenant_id)
    has_chunks = await db.scalar(
        select(DocumentChunk.id).where(DocumentChunk.document_id == document_id).limit(1)
    )
    if has_chunks is not None:
        await _set_document(db, tenant_id, document_id, "ready", None)
    else:
        await _mark_failed(db, tenant_id, document_id, CANCELLED_MESSAGE)


async def _mark_failed(db: AsyncSession, tenant_id: UUID, document_id: UUID, error: str) -> None:
    await _set_document(db, tenant_id, document_id, "failed", error)
