import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

AUDIT_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
ACTIVE_STATUSES = ("queued", "running")


class Audit(UUIDMixin, TimestampMixin, Base):
    """One audit run for a client (FR-AUD-01, 06, 08). `url` is a snapshot of the address that
    was audited, since the client's website can change later. `summary` holds the category
    scores, counts per severity and crawl totals; `raw` holds the per-page crawl facts."""

    __tablename__ = "audits"
    __table_args__ = (Index("ix_audits_client_created", "client_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="queued", nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditFinding(UUIDMixin, TimestampMixin, Base):
    """An individual issue. `code` is a stable rule id, so two audits can be compared."""

    __tablename__ = "audit_findings"
    __table_args__ = (Index("ix_audit_findings_audit_severity", "audit_id", "severity"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    audit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
