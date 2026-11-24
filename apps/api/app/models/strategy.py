import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Strategy(UUIDMixin, TimestampMixin, Base):
    """FR-RAG-05 / FR-STR: one generated monthly strategy version. `sources` is a
    snapshot (chunk id, document title, excerpt) so it outlives deleted documents.
    cost_usd is NULL when no price is known for the model."""

    __tablename__ = "strategies"
    __table_args__ = (
        UniqueConstraint("client_id", "month", "version", name="uq_strategy_version"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="draft", nullable=False)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model_used: Mapped[str] = mapped_column(String(200), nullable=False)
    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    # SRS §10.4 grounding post-check: figures in the plan that the input never contained.
    warnings: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
