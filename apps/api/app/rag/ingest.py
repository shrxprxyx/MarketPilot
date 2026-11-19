"""Background ingestion: chunk -> embed -> store (FR-RAG-01, FR-RAG-04)."""
import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.rls import set_rls_context
from app.models.document import Document, DocumentChunk
from app.rag.chunking import chunk_text
from app.rag.embeddings import embed_documents

logger = logging.getLogger(__name__)
EMBED_BATCH = 32


async def ingest_document(db: AsyncSession, tenant_id: UUID, document_id: UUID) -> None:
    """Idempotent: replaces any existing chunks, so it doubles as the re-index action."""
    await set_rls_context(db, tenant_id=tenant_id)
    doc = await db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if doc is None:
        return  # deleted before the job ran
    doc.status, doc.error = "processing", None
    await db.commit()

    try:
        await set_rls_context(db, tenant_id=tenant_id)  # commit ended the transaction
        chunks = chunk_text(doc.content)
        vectors: list[list[float]] = []
        for i in range(0, len(chunks), EMBED_BATCH):
            vectors.extend(await embed_documents(chunks[i : i + EMBED_BATCH]))
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
    except Exception:
        logger.exception("Document ingestion failed", extra={"document_id": str(document_id)})
        await db.rollback()
        await set_rls_context(db, tenant_id=tenant_id)
        failed = await db.get(Document, document_id)
        if failed:
            failed.status, failed.error = "failed", "Indexing failed. Try re-indexing."
            await db.commit()
