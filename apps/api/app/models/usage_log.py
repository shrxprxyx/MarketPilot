import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class UsageLog(UUIDMixin, TimestampMixin, Base):
    """FR-BYOM-04: one row per successful model call. cost_usd is NULL when no
    price is known for the model (local models are priced at zero)."""

    __tablename__ = "usage_logs"
    # Budget spend and the usage dashboard both filter by tenant and a created_at window.
    __table_args__ = (Index("ix_usage_logs_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_connections.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
