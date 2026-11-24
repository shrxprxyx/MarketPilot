"""Background jobs: status, list, cancel and live progress over SSE (SRS §8)."""
import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.auth.jwt import decode_access_token
from app.auth.stream_ticket import redeem_ticket
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.pagination import decode_cursor, encode_cursor
from app.core.redis import get_redis
from app.core.request import client_ip
from app.db.rls import set_rls_context
from app.db.session import get_db
from app.jobs.progress import channel, snapshot
from app.jobs.service import cancel_job
from app.models.job import TERMINAL_STATUSES, Job
from app.models.membership import Membership

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])

DB = Annotated[AsyncSession, Depends(get_db)]
WRITER = require_role("admin", "manager")

HEARTBEAT_SECONDS = 15
MAX_STREAM_SECONDS = 30 * 60


class JobOut(BaseModel):
    job_id: UUID
    type: str
    status: str
    progress: int
    message: str | None
    error: str | None
    result_ref: dict[str, Any] | None


class JobListOut(BaseModel):
    items: list[JobOut]
    next_cursor: str | None


async def _job_or_404(db: AsyncSession, tenant_id: UUID, job_id: UUID) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id))
    if job is None:
        raise ProblemException(404, "Not Found", "Job not found.")
    return job


@router.get("", response_model=JobListOut)
async def list_jobs(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    status: str | None = None,
    type: str | None = None,  # noqa: A002 - query parameter name
) -> JobListOut:
    stmt = (
        select(Job)
        .where(Job.tenant_id == current.tenant_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit + 1)
    )
    if status:
        stmt = stmt.where(Job.status == status)
    if type:
        stmt = stmt.where(Job.type == type)
    if cursor:
        try:
            created_at, row_id = decode_cursor(cursor)
        except ValueError as exc:
            raise ProblemException(400, "Bad Request", "Invalid cursor.") from exc
        stmt = stmt.where(tuple_(Job.created_at, Job.id) < (created_at, row_id))
    rows = list((await db.execute(stmt)).scalars().all())
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if len(rows) > limit and items else None
    )
    return JobListOut(items=[JobOut(**snapshot(j)) for j in items], next_cursor=next_cursor)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], db: DB
) -> JobOut:
    return JobOut(**snapshot(await _job_or_404(db, current.tenant_id, job_id)))


@router.delete("/{job_id}", response_model=JobOut)
async def cancel(
    job_id: UUID, request: Request, current: Annotated[CurrentUser, WRITER], db: DB
) -> JobOut:
    """Cancel a queued or running job (admins and managers). A job the worker already
    finished cannot be cancelled."""
    job = await _job_or_404(db, current.tenant_id, job_id)
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="job.cancelled",
        entity="job",
        entity_id=job.id,
        meta={"type": job.type},
        ip=client_ip(request),
    )
    await cancel_job(db, job)  # commits the audit row together with the status change
    return JobOut(**snapshot(job))


async def _stream_identity(
    request: Request, ticket: str | None, db: AsyncSession
) -> tuple[UUID, UUID]:
    """Who is opening the stream: a single-use ticket (browsers), or a bearer token (API
    clients that can set headers). Returns (user_id, tenant_id) after the membership check."""
    if ticket:
        holder = await redeem_ticket(ticket)
        if holder is None:
            raise ProblemException(401, "Unauthorized", "Invalid, expired or used stream ticket.")
        user_id, tenant_id = holder.user_id, holder.tenant_id
    else:
        header = request.headers.get("authorization", "")
        payload = decode_access_token(header[7:]) if header.lower().startswith("bearer ") else None
        if payload is None:
            raise ProblemException(
                401, "Unauthorized", "A stream ticket or bearer token is required."
            )
        user_id, tenant_id = UUID(payload["sub"]), UUID(payload["tenant_id"])

    await set_rls_context(db, tenant_id=tenant_id, user_id=user_id)
    active = await db.scalar(
        select(Membership.id).where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
        )
    )
    if active is None:
        raise ProblemException(403, "Forbidden", "Not an active member of this tenant.")
    return user_id, tenant_id


def _sse(event: dict[str, Any]) -> str:
    return f"event: job\ndata: {json.dumps(event)}\n\n"


@router.get("/{job_id}/events")
async def job_events(
    job_id: UUID, request: Request, db: DB, ticket: str | None = None
) -> StreamingResponse:
    """Server-Sent Events for one job: the current state first, then every change until the
    job finishes. Authorise with `?ticket=` from POST /auth/stream-ticket."""
    _, tenant_id = await _stream_identity(request, ticket, db)
    # Subscribe before reading the row so a change that lands in between is not lost.
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(channel(tenant_id, job_id))
    try:
        job = await _job_or_404(db, tenant_id, job_id)
    except ProblemException:
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        raise
    first = snapshot(job)
    await db.rollback()  # nothing else needs this session while the stream is open

    async def stream() -> AsyncGenerator[str, None]:
        deadline = time.monotonic() + MAX_STREAM_SECONDS
        try:
            yield "retry: 3000\n\n"
            yield _sse(first)
            if first["status"] in TERMINAL_STATUSES:
                return
            while time.monotonic() < deadline:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS
                )
                if msg is None:
                    yield ": ping\n\n"  # keeps proxies from closing an idle stream
                    continue
                data = msg["data"]
                event = json.loads(data if isinstance(data, str) else data.decode())
                yield _sse(event)
                if event.get("status") in TERMINAL_STATUSES:
                    return
        except asyncio.CancelledError:  # the client went away
            raise
        finally:
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
