import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

TASK_TYPES = ("strategy", "content", "analysis", "embedding_summary")


class TaskModelRoute(UUIDMixin, TimestampMixin, Base):
    """FR-BYOM-03: which connection/model handles a task type, with an optional fallback."""

    __tablename__ = "task_model_routes"
    __table_args__ = (UniqueConstraint("tenant_id", "task_type", name="uq_route_tenant_task"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_connections.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, server_default="0.7", nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, server_default="2048", nullable=False)
    fallback_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_connections.id", ondelete="SET NULL"), nullable=True
    )
    fallback_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
