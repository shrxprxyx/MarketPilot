import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.audit.runner import run_audit
from app.config import settings
from app.core.logging import configure_logging, job_id_var, tenant_id_var
from app.jobs.celery_app import celery_app


async def _run(tenant_id: UUID, audit_id: UUID, job_id: UUID) -> None:
    # Each task gets its own loop, so use a throwaway engine instead of the shared pool.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await run_audit(session, tenant_id, audit_id, job_id)
    finally:
        await engine.dispose()


# No automatic retry: a crawl is long, and the runner already turns site problems into
# findings. An unexpected failure is reported on the audit so the user can run it again.
@celery_app.task(name="audit.run_website_audit")
def website_audit_task(tenant_id: str, audit_id: str, job_id: str) -> None:
    configure_logging()  # the worker does not import app.main, so set up JSON logs here
    tenant_id_var.set(tenant_id)
    job_id_var.set(job_id)
    asyncio.run(_run(UUID(tenant_id), UUID(audit_id), UUID(job_id)))

