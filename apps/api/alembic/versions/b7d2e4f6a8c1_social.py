"""social accounts, posts and daily totals (FR-AUD-09, 10)

Revision ID: b7d2e4f6a8c1
Revises: a3f1c9d2e7b4
Create Date: 2026-11-28 12:00:00.000000

"""
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = 'b7d2e4f6a8c1'
down_revision: str | Sequence[str] | None = 'a3f1c9d2e7b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("social_accounts", "social_posts", "social_daily")


def _base() -> list[Any]:
    return [
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    ]


def _int(name: str) -> Any:
    return sa.Column(name, sa.Integer(), server_default='0', nullable=False)


def upgrade() -> None:
    op.create_table(
        'social_accounts', *_base(),
        sa.Column('client_id', sa.UUID(), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('handle', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_id', 'platform', 'handle'),
    )
    op.create_table(
        'social_posts', *_base(),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('ref', sa.String(length=500), nullable=False),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=True),
        sa.Column('format', sa.String(length=40), nullable=True),
        _int('impressions'), _int('reach'), _int('likes'), _int('comments'),
        _int('shares'), _int('clicks'),
        sa.ForeignKeyConstraint(['account_id'], ['social_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'ref'),
    )
    op.create_table(
        'social_daily', *_base(),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('followers', sa.Integer(), nullable=True),
        _int('reach'), _int('impressions'),
        sa.ForeignKeyConstraint(['account_id'], ['social_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'day'),
    )
    for table in TABLES:
        op.create_index(op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
              WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
