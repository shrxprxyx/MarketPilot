from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.client import Client


class BrandProfile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "brand_profiles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    voice: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tone: Mapped[str | None] = mapped_column(String(120), nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    do_rules: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    dont_rules: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    sample_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    client: Mapped[Client] = relationship(back_populates="brand_profile")
