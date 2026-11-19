from decimal import Decimal

from sqlalchemy import Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ModelPricing(UUIDMixin, TimestampMixin, Base):
    """Global (not tenant-scoped) price table, USD per million tokens (SRS §6.2)."""

    __tablename__ = "model_pricing"
    __table_args__ = (UniqueConstraint("provider", "model", name="uq_pricing_provider_model"),)

    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    input_per_mtok: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    output_per_mtok: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
