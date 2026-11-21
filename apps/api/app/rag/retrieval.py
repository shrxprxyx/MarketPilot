"""Hybrid retrieval (FR-RAG-03, SRS §10.3): top 20 by vector cosine similarity and
top 20 by full-text rank, fused with reciprocal rank fusion, trimmed to a token
budget. Always filtered by tenant and client (RLS is the backstop)."""
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.rag.chunking import CHARS_PER_TOKEN
from app.rag.embeddings import embed_query

CANDIDATES = 20
RRF_K = 60


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    source_type: str
    chunk_index: int
    text: str
    score: float


def rrf_fuse(rankings: list[list[UUID]], k: int = RRF_K) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


async def search_chunks(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    client_id: UUID,
    query: str,
    k: int = 8,
    source_type: str | None = None,
    exclude_source_types: Sequence[str] = (),
    token_budget: int = 3000,
) -> list[RetrievedChunk]:
    base_filters = [
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.client_id == client_id,
        Document.status == "ready",
    ]
    if source_type:
        base_filters.append(Document.source_type == source_type)
    if exclude_source_types:
        base_filters.append(Document.source_type.not_in(exclude_source_types))

    qvec = await embed_query(query)
    vector_ids = list(
        await db.scalars(
            select(DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*base_filters)
            .order_by(DocumentChunk.embedding.cosine_distance(qvec))
            .limit(CANDIDATES)
        )
    )
    tsquery = func.websearch_to_tsquery("english", query)
    fts_ids = list(
        await db.scalars(
            select(DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*base_filters, DocumentChunk.tsv.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(DocumentChunk.tsv, tsquery).desc())
            .limit(CANDIDATES)
        )
    )

    fused = rrf_fuse([vector_ids, fts_ids])[:k]
    if not fused:
        return []
    rows = (
        await db.execute(
            select(DocumentChunk, Document.title, Document.source_type)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_([cid for cid, _ in fused]))
        )
    ).all()
    by_id = {chunk.id: (chunk, title, stype) for chunk, title, stype in rows}

    results: list[RetrievedChunk] = []
    used = 0
    for chunk_id, score in fused:
        chunk, title, stype = by_id[chunk_id]
        cost = len(chunk.text) // CHARS_PER_TOKEN
        if results and used + cost > token_budget:
            break
        used += cost
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=title,
                source_type=stype,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                score=score,
            )
        )
    return results
