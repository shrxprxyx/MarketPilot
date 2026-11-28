import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

PLATFORMS = ("facebook", "instagram", "linkedin")


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _account() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False
    )


def _count() -> Mapped[int]:
    return mapped_column(Integer, server_default="0", nullable=False)


class SocialAccount(UUIDMixin, TimestampMixin, Base):
    """A client's account on one platform (FR-AUD-09)."""

    __tablename__ = "social_accounts"
    __table_args__ = (UniqueConstraint("client_id", "platform", "handle"),)

    tenant_id: Mapped[uuid.UUID] = _tenant()
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    handle: Mapped[str] = mapped_column(String(200), nullable=False)


class SocialPost(UUIDMixin, TimestampMixin, Base):
    """One imported post. `ref` is the export's own id or link (else date + title), so importing
    the same file twice updates rows instead of duplicating them."""

    __tablename__ = "social_posts"
    __table_args__ = (UniqueConstraint("account_id", "ref"),)

    tenant_id: Mapped[uuid.UUID] = _tenant()
    account_id: Mapped[uuid.UUID] = _account()
    ref: Mapped[str] = mapped_column(String(500), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    format: Mapped[str | None] = mapped_column(String(40), nullable=True)
    impressions: Mapped[int] = _count()
    reach: Mapped[int] = _count()
    likes: Mapped[int] = _count()
    comments: Mapped[int] = _count()
    shares: Mapped[int] = _count()
    clicks: Mapped[int] = _count()


class SocialDaily(UUIDMixin, TimestampMixin, Base):
    """Account totals for one day: the follower count and the reach/impressions trend."""

    __tablename__ = "social_daily"
    __table_args__ = (UniqueConstraint("account_id", "day"),)

    tenant_id: Mapped[uuid.UUID] = _tenant()
    account_id: Mapped[uuid.UUID] = _account()
    day: Mapped[date] = mapped_column(Date, nullable=False)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reach: Mapped[int] = _count()
    impressions: Mapped[int] = _count()
