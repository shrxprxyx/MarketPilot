"""FR-TEN-06: security-relevant actions get written to audit_log.

`log_audit` only stages the row (db.add) — it never commits on its own. The
caller's existing commit persists it atomically with the change it describes,
so the audit entry and the action it records can never diverge from each other.
"""
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


def log_audit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
    action: str,
    entity: str,
    entity_id: UUID | None = None,
    meta: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            meta=meta,
            ip=ip,
        )
    )
