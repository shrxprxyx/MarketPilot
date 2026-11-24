"""strategy grounding warnings

Revision ID: e9f4b2a6c8d1
Revises: d8e3a1f5b7c9
Create Date: 2026-11-25 01:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e9f4b2a6c8d1'
down_revision: str | Sequence[str] | None = 'd8e3a1f5b7c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'strategies',
        sa.Column(
            'warnings',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('strategies', 'warnings')
