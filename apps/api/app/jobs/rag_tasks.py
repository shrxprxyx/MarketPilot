import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.jobs.celery_app import celery_app
from app.rag.ingest import ingest_document


async def _run(tenant_id: UUID, document_id: UUID) -> None:
    # Each task gets its own loop, so use a throwaway engine instead of the shared pool.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await ingest_document(session, tenant_id, document_id)
    finally:
        await engine.dispose()


@celery_app.task(name="rag.ingest_document")
def ingest_task(tenant_id: str, document_id: str) -> None:
    asyncio.run(_run(UUID(tenant_id), UUID(document_id)))
