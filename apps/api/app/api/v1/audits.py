"""Website audits (FR-AUD-01, 06). Admins and managers start audits (§2.2); every role can read
them. The crawl itself runs in the worker and reports through a job."""
import hashlib
import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.queue import enqueue_website_audit
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.pagination import decode_cursor, encode_cursor
from app.core.rate_limit import rate_limit
from app.core.request import client_ip
from app.db.rls import set_rls_context
from app.db.session import get_db
from app.jobs.progress import update_job
from app.jobs.service import create_job, replay_or_none, validate_idempotency_key
from app.models.audit import ACTIVE_STATUSES, Audit, AuditFinding
from app.models.client import Client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["audits"])
AUDIT_JOB = "audit.website"

DB = Annotated[AsyncSession, Depends(get_db)]
WRITER = require_role("admin", "manager")
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class AuditIn(BaseModel):
    # Social and competitor audits arrive with their own engines (FR-AUD-09 to 11).
    type: Literal["website"] = "website"


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    type: str
    url: str
    status: str
    score: int | None
    summary: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    job_id: UUID | None = None


class AuditListOut(BaseModel):
    items: list[AuditOut]
    next_cursor: str | None


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    category: str
    severity: str
    title: str
    detail: str
    url: str | None
    recommendation: str
    metric: dict[str, Any]


class FindingListOut(BaseModel):
    items: list[FindingOut]


async def _client_or_404(db: AsyncSession, current: CurrentUser, client_id: UUID) -> Client:
    # The explicit tenant filter is defence in depth on top of RLS (§3.4).
    client = await db.scalar(
        select(Client).where(Client.id == client_id, Client.tenant_id == current.tenant_id)
    )
    if client is None:
        raise ProblemException(404, "Not Found", "Client not found.")
    return client


async def _audit_or_404(db: AsyncSession, current: CurrentUser, audit_id: UUID) -> Audit:
    audit = await db.scalar(
        select(Audit).where(Audit.id == audit_id, Audit.tenant_id == current.tenant_id)
    )
    if audit is None:
        raise ProblemException(404, "Not Found", "Audit not found.")
    return audit


@router.post(
    "/clients/{client_id}/audits",
    response_model=AuditOut,
    status_code=202,
    dependencies=[rate_limit("audits.start", user=10, tenant=30)],
)
async def start_audit(
    client_id: UUID,
    body: AuditIn,
    request: Request,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> AuditOut:
    client = await _client_or_404(db, current, client_id)
    if client.status == "archived":
        raise ProblemException(409, "Conflict", "Restore this client before auditing it.")
    if not client.website_url:
        raise ProblemException(
            422, "Unprocessable Entity", "Add a website URL to this client before auditing it."
        )
    key = validate_idempotency_key(request.headers.get("Idempotency-Key"))
    request_hash = hashlib.sha256(f"audit|{client_id}|{body.type}".encode()).hexdigest()
    replay = await replay_or_none(
        db, current.tenant_id, key, job_type=AUDIT_JOB, request_hash=request_hash
    )
    if replay is not None:
        original = await _audit_or_404(db, current, UUID(replay.payload["audit_id"]))
        return AuditOut.model_validate(original).model_copy(update={"job_id": replay.id})

    running = await db.scalar(
        select(Audit.id).where(
            Audit.client_id == client_id, Audit.status.in_(ACTIVE_STATUSES)
        ).limit(1)
    )
    if running is not None:  # crawling a site is not free for the site's owner either
        raise ProblemException(409, "Conflict", "An audit is already running for this client.")

    audit = Audit(
        tenant_id=current.tenant_id,
        client_id=client_id,
        type=body.type,
        url=client.website_url,
        created_by=current.user.id,
    )
    db.add(audit)
    await db.flush()
    job = await create_job(
        db,
        tenant_id=current.tenant_id,
        job_type=AUDIT_JOB,
        created_by=current.user.id,
        payload={
            "audit_id": str(audit.id),
            "client_id": str(client_id),
            "request_hash": request_hash,
        },
        idempotency_key=key,
    )
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="audit.started",
        entity="audit",
        entity_id=audit.id,
        meta={"client_id": str(client_id), "url": audit.url, "type": audit.type},
        ip=client_ip(request),
    )
    await db.commit()
    out = AuditOut.model_validate(audit).model_copy(update={"job_id": job.id})
    try:
        enqueue_website_audit(current.tenant_id, audit.id, job.id)
    except Exception:
        logger.exception("Could not queue the audit")
        # A broken queue must not turn a saved audit into a 500; the audit shows as failed.
        await set_rls_context(db, tenant_id=current.tenant_id)  # the commit ended the transaction
        audit.status, audit.error = "failed", "The audit queue is unavailable. Try again."
        await db.commit()
        await update_job(
            db, current.tenant_id, job.id, status="failed", error="The audit queue is unavailable.",
            message="Could not start the audit",
        )
        out = AuditOut.model_validate(audit).model_copy(update={"job_id": job.id})
    return out


@router.get("/clients/{client_id}/audits", response_model=AuditListOut)
async def list_audits(
    client_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> AuditListOut:
    await _client_or_404(db, current, client_id)
    stmt = (
        select(Audit)
        .where(Audit.client_id == client_id, Audit.tenant_id == current.tenant_id)
        .order_by(Audit.created_at.desc(), Audit.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        try:
            created_at, row_id = decode_cursor(cursor)
        except ValueError as exc:
            raise ProblemException(400, "Bad Request", "Invalid cursor.") from exc
        stmt = stmt.where(tuple_(Audit.created_at, Audit.id) < (created_at, row_id))
    rows = list((await db.execute(stmt)).scalars().all())
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if len(rows) > limit and items else None
    )
    return AuditListOut(
        items=[AuditOut.model_validate(a) for a in items], next_cursor=next_cursor
    )


@router.get("/audits/{audit_id}", response_model=AuditOut)
async def get_audit(
    audit_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], db: DB
) -> AuditOut:
    return AuditOut.model_validate(await _audit_or_404(db, current, audit_id))


@router.get("/audits/{audit_id}/findings", response_model=FindingListOut)
async def list_findings(
    audit_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
    severity: Literal["critical", "high", "medium", "low"] | None = None,
    category: Literal["technical", "on_page", "links", "mobile"] | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> FindingListOut:
    await _audit_or_404(db, current, audit_id)
    rank = case(SEVERITY_ORDER, value=AuditFinding.severity, else_=9)
    stmt = (
        select(AuditFinding)
        .where(AuditFinding.audit_id == audit_id, AuditFinding.tenant_id == current.tenant_id)
        .order_by(rank, AuditFinding.code, AuditFinding.url, AuditFinding.id)
        .limit(limit)
    )
    if severity:
        stmt = stmt.where(AuditFinding.severity == severity)
    if category:
        stmt = stmt.where(AuditFinding.category == category)
    rows = (await db.execute(stmt)).scalars().all()
    return FindingListOut(items=[FindingOut.model_validate(r) for r in rows])
