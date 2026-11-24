import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.logging import configure_logging, job_id_var, tenant_id_var
from app.jobs.celery_app import celery_app
from app.rag.ingest import ingest_document

MAX_RETRIES = 3  # attempts after the first, with exponential backoff (SRS §3.5)


async def _run(
    tenant_id: UUID, document_id: UUID, job_id: UUID | None, will_retry: bool
) -> bool:
    # Each task gets its own loop, so use a throwaway engine instead of the shared pool.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await ingest_document(
                session, tenant_id, document_id, job_id, will_retry=will_retry
            )
    finally:
        await engine.dispose()


@celery_app.task(name="rag.ingest_document", bind=True, max_retries=MAX_RETRIES)
def ingest_task(
    self: Any, tenant_id: str, document_id: str, job_id: str | None = None
) -> None:
    configure_logging()  # the worker does not import app.main, so set up JSON logs here
    tenant_id_var.set(tenant_id)
    job_id_var.set(job_id)
    will_retry = self.request.retries < MAX_RETRIES
    ok = asyncio.run(
        _run(UUID(tenant_id), UUID(document_id), UUID(job_id) if job_id else None, will_retry)
    )
    if not ok and will_retry:
        raise self.retry(countdown=2 ** (self.request.retries + 1))  # 2s, 4s, 8s
