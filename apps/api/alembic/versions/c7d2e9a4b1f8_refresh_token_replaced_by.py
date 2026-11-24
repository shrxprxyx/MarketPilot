"""refresh token replaced_by for reuse detection

Revision ID: c7d2e9a4b1f8
Revises: a1c4e7b9d2f6
Create Date: 2026-11-24 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d2e9a4b1f8'
down_revision: str | Sequence[str] | None = 'a1c4e7b9d2f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('refresh_tokens', sa.Column('replaced_by', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_refresh_tokens_replaced_by_refresh_tokens',
        'refresh_tokens', 'refresh_tokens', ['replaced_by'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_refresh_tokens_replaced_by_refresh_tokens', 'refresh_tokens', type_='foreignkey')
    op.drop_column('refresh_tokens', 'replaced_by')
