from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.membership import Membership


class Tenant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(32), server_default="free", nullable=False)
    # FR-BYOM-05: optional monthly AI budget; hard_stop refuses calls once spend reaches it.
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    hard_stop: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)

    members: Mapped[list[Membership]] = relationship(back_populates="tenant")