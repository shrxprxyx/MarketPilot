"""Retrieval hit-rate report (FR-RAG-06).

Indexes a small fixed corpus (rag_eval/corpus) for a throwaway tenant, runs every golden
question (rag_eval/golden_questions.json) through the real hybrid retrieval, and reports the
hit rate at k: the share of questions whose expected document appears among the top k chunks.

Needs the same Postgres (pgvector) and .env as the API; no worker, no LLM and no network
access beyond the one-off embedding model download. The throwaway tenant is deleted afterwards.

    uv run python -m rag_eval.run                        # report hit@1, hit@3, hit@5
    uv run python -m rag_eval.run --k 3 8 --min 0.85     # exit 1 if hit@8 < 0.85
"""
import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import delete

import app.db.base_imports  # noqa: F401  (registers every model so the FKs resolve)
import app.db.engine as db_engine
from app.db.rls import set_rls_context
from app.models.client import Client
from app.models.document import Document
from app.models.tenant import Tenant
from app.rag.extract import content_hash
from app.rag.ingest import ingest_document
from app.rag.retrieval import search_chunks

HERE = Path(__file__).parent
DEFAULT_KS = (1, 3, 5)


def hit_rate(ranked_titles: Sequence[Sequence[str]], expected: Sequence[str], k: int) -> float:
    """Share of questions whose expected title is among the first k retrieved chunks."""
    if len(ranked_titles) != len(expected):
        raise ValueError("one ranking is needed per expected title")
    if not expected:
        raise ValueError("no questions to score")
    pairs = zip(ranked_titles, expected, strict=True)
    hits = sum(1 for ranked, want in pairs if want in ranked[:k])
    return hits / len(expected)


def load_questions() -> list[dict[str, str]]:
    data: list[dict[str, str]] = json.loads((HERE / "golden_questions.json").read_text("utf-8"))
    return data


def load_corpus() -> dict[str, str]:
    return {p.name: p.read_text("utf-8").strip() for p in sorted((HERE / "corpus").glob("*.md"))}


async def retrieve_all(questions: list[dict[str, str]], k: int) -> list[list[str]]:
    """Index the corpus for a throwaway tenant and return, per question, the titles of the
    top-k retrieved chunks in rank order. The tenant is always removed again."""
    tenant_id, client_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with db_engine.AsyncSessionLocal() as db:
            db.add(Tenant(id=tenant_id, name="RAG eval", slug=f"rag-eval-{tenant_id.hex[:12]}"))
            await db.flush()
            await set_rls_context(db, tenant_id=tenant_id)
            db.add(Client(id=client_id, tenant_id=tenant_id, name="Brewline Coffee Roasters"))
            await db.flush()
            doc_ids = []
            for title, text in load_corpus().items():
                doc = Document(
                    tenant_id=tenant_id,
                    client_id=client_id,
                    source_type="brand_doc",
                    title=title,
                    content=text,
                    content_hash=content_hash(text),
                )
                db.add(doc)
                await db.flush()
                doc_ids.append(doc.id)
            await db.commit()
        for doc_id in doc_ids:
            async with db_engine.AsyncSessionLocal() as db:
                await ingest_document(db, tenant_id, doc_id)

        rankings: list[list[str]] = []
        async with db_engine.AsyncSessionLocal() as db:
            await set_rls_context(db, tenant_id=tenant_id)
            for q in questions:
                found = await search_chunks(
                    db,
                    tenant_id=tenant_id,
                    client_id=client_id,
                    query=q["question"],
                    k=k,
                    token_budget=10**9,  # score ranking quality, not the prompt-size trim
                )
                rankings.append([c.document_title for c in found])
        return rankings
    finally:
        async with db_engine.AsyncSessionLocal() as db:
            await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await db.commit()


async def evaluate(ks: Sequence[int]) -> dict[str, Any]:
    questions = load_questions()
    rankings = await retrieve_all(questions, max(ks))
    expected = [q["expected"] for q in questions]
    return {
        "questions": len(questions),
        "hit_rate": {k: hit_rate(rankings, expected, k) for k in ks},
        "misses": {
            k: [
                {"question": q["question"], "expected": q["expected"], "got": ranked[:k]}
                for q, ranked in zip(questions, rankings, strict=True)
                if q["expected"] not in ranked[:k]
            ]
            for k in ks
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report retrieval hit rate at k (FR-RAG-06).")
    parser.add_argument("--k", type=int, nargs="+", default=list(DEFAULT_KS), help="values of k")
    parser.add_argument("--min", type=float, default=None, help="fail if hit@(largest k) is lower")
    args = parser.parse_args(argv)
    if any(k < 1 for k in args.k):
        parser.error("k must be at least 1")

    result = asyncio.run(evaluate(sorted(set(args.k))))
    print(f"Golden questions: {result['questions']}")
    for k, rate in result["hit_rate"].items():
        print(f"  hit@{k}: {rate:.0%}")
    largest = max(result["hit_rate"])
    for miss in result["misses"][largest]:
        print(f"  miss@{largest}: {miss['question']!r}")
        print(f"      expected {miss['expected']}, got {miss['got']}")
    if args.min is not None and result["hit_rate"][largest] < args.min:
        print(f"FAIL: hit@{largest} {result['hit_rate'][largest]:.0%} is below {args.min:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
