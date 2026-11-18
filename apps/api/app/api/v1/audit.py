from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, require_role
from app.core.errors import ProblemException
from app.core.pagination import decode_cursor, encode_cursor
from app.db.session import get_db
from app.models.audit_log import AuditLog

router = APIRouter(prefix="/audit-log", tags=["audit"])

DB = Annotated[AsyncSession, Depends(get_db)]
# FR-TEN-06 doesn't name a role here, but it's the same security-sensitive
# audience as /members — reads are admin-only.
ADMIN = require_role("admin")


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID | None
    action: str
    entity: str
    entity_id: UUID | None
    meta: dict[str, Any] | None
    ip: str | None
    created_at: datetime


class AuditLogListOut(BaseModel):
    items: list[AuditLogOut]
    next_cursor: str | None


@router.get("", response_model=AuditLogListOut)
async def list_audit_log(
    current: Annotated[CurrentUser, ADMIN],
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    action: str | None = None,
    entity: str | None = None,
) -> AuditLogListOut:
    stmt = select(AuditLog).where(AuditLog.tenant_id == current.tenant_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)

    if cursor:
        try:
            created_at, row_id = decode_cursor(cursor)
        except ValueError as exc:
            raise ProblemException(400, "Bad Request", "Invalid cursor.") from exc
        stmt = stmt.where(tuple_(AuditLog.created_at, AuditLog.id) < (created_at, row_id))

    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    )
    return AuditLogListOut(
        items=[AuditLogOut.model_validate(r) for r in items], next_cursor=next_cursor
    )
