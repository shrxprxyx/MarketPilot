"""tenant branding (FR-TEN-07)

Revision ID: d8e3a1f5b7c9
Revises: c7d2e9a4b1f8
Create Date: 2026-11-25 01:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8e3a1f5b7c9'
down_revision: str | Sequence[str] | None = 'c7d2e9a4b1f8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tenants', sa.Column('logo_url', sa.String(length=500), nullable=True))
    op.add_column('tenants', sa.Column('primary_color', sa.String(length=7), nullable=True))
    op.add_column('tenants', sa.Column('report_footer', sa.String(length=300), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tenants', 'report_footer')
    op.drop_column('tenants', 'primary_color')
    op.drop_column('tenants', 'logo_url')
