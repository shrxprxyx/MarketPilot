"""Job state changes and their real-time fan-out (SRS §3.5).

Every change is written to the `jobs` row (the source of truth) and then published on a
Redis channel scoped to the tenant and job, which the SSE endpoint relays to the browser.
Publishing is best effort: a Redis outage must never fail the job it is reporting on, and a
client that misses an event still gets the current state from the row when it reconnects.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from redis import asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.rls import set_rls_context
from app.models.job import TERMINAL_STATUSES, Job

logger = logging.getLogger(__name__)


def channel(tenant_id: UUID | str, job_id: UUID | str) -> str:
    return f"job:{tenant_id}:{job_id}"


def snapshot(job: Job) -> dict[str, Any]:
    """The event / API representation of a job's current state."""
    return {
        "job_id": str(job.id),
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "result_ref": job.result_ref,
    }


async def publish(job: Job) -> None:
    """Best-effort publish with a short-lived connection, so it works from any event loop
    (the Celery worker runs each task in a fresh one)."""
    try:
        client = aioredis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
        try:
            await client.publish(channel(job.tenant_id, job.id), json.dumps(snapshot(job)))
        finally:
            await client.aclose()
    except Exception:
        logger.warning("Could not publish job event", exc_info=True)


async def _load(db: AsyncSession, tenant_id: UUID, job_id: UUID) -> Job | None:
    await set_rls_context(db, tenant_id=tenant_id)
    job: Job | None = await db.scalar(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )
    return job


async def update_job(
    db: AsyncSession,
    tenant_id: UUID,
    job_id: UUID,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
    result_ref: dict[str, Any] | None = None,
) -> Job | None:
    """Apply a change, commit, and publish. A job that already finished (for example one the
    user cancelled while the worker was busy) is left exactly as it is."""
    job = await _load(db, tenant_id, job_id)
    if job is None or job.status in TERMINAL_STATUSES:
        return job
    now = datetime.now(timezone.utc)
    if status is not None:
        job.status = status
        if status == "running" and job.started_at is None:
            job.started_at = now
        if status in TERMINAL_STATUSES:
            job.finished_at = now
    if progress is not None:
        job.progress = max(0, min(100, progress))
    if message is not None:
        job.message = message[:300]
    if error is not None:
        job.error = error
    if result_ref is not None:
        job.result_ref = result_ref
    if job.status == "succeeded":
        job.progress = 100
    await db.commit()
    await publish(job)
    return job


async def job_status(db: AsyncSession, tenant_id: UUID, job_id: UUID) -> str | None:
    job = await _load(db, tenant_id, job_id)
    status = job.status if job else None
    await db.rollback()  # end the read-only transaction; the caller's next step opens its own
    return status


async def is_cancelled(db: AsyncSession, tenant_id: UUID, job_id: UUID) -> bool:
    return await job_status(db, tenant_id, job_id) == "cancelled"

