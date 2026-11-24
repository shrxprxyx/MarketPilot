"""Creating and cancelling jobs from the API side (SRS §3.5, §8)."""
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemException
from app.jobs.progress import publish
from app.models.job import TERMINAL_STATUSES, Job

_KEY = re.compile(r"^[A-Za-z0-9._:\-]{8,100}$")


def validate_idempotency_key(key: str | None) -> str | None:
    if key is None:
        return None
    if not _KEY.match(key):
        raise ProblemException(
            422,
            "Unprocessable Entity",
            "Idempotency-Key must be 8-100 characters: letters, digits and . _ : -",
        )
    return key


async def find_by_key(db: AsyncSession, tenant_id: UUID, key: str) -> Job | None:
    job: Job | None = await db.scalar(
        select(Job).where(Job.tenant_id == tenant_id, Job.idempotency_key == key)
    )
    return job


async def replay_or_none(
    db: AsyncSession, tenant_id: UUID, key: str | None, *, job_type: str, request_hash: str
) -> Job | None:
    """If `key` was already used, return that job (the caller replays its response). Reusing a
    key for a different request is a client bug and is refused rather than silently ignored."""
    if key is None:
        return None
    job = await find_by_key(db, tenant_id, key)
    if job is None:
        return None
    if job.type != job_type or job.payload.get("request_hash") != request_hash:
        raise ProblemException(
            422,
            "Unprocessable Entity",
            "This Idempotency-Key was already used with a different request.",
        )
    return job


async def create_job(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    job_type: str,
    created_by: UUID | None,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> Job:
    """Stages the row (flushed, not committed) so it commits with the change that caused it."""
    job = Job(
        tenant_id=tenant_id,
        type=job_type,
        created_by=created_by,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    try:
        await db.flush()
    except IntegrityError:  # lost a race with an identical key
        await db.rollback()
        raise ProblemException(
            409, "Conflict", "This request is already being processed."
        ) from None
    return job


async def cancel_job(db: AsyncSession, job: Job) -> Job:
    """Queued and running jobs can be cancelled; the worker notices at its next checkpoint."""
    if job.status in TERMINAL_STATUSES:
        raise ProblemException(409, "Conflict", f"The job already {job.status}.")
    job.status = "cancelled"
    job.message = "Cancelled."
    job.finished_at = datetime.now(timezone.utc)
    await db.commit()
    await publish(job)
    return job
