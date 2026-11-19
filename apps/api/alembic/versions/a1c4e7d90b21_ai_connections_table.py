"""ai_connections table

Revision ID: a1c4e7d90b21
Revises: 8fe65ac3f66f
Create Date: 2026-11-19 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1c4e7d90b21'
down_revision: str | Sequence[str] | None = '8fe65ac3f66f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ai_connections',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('base_url', sa.String(length=500), nullable=True),
    sa.Column('api_key_enc', sa.String(), nullable=True),
    sa.Column('key_last4', sa.String(length=4), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_connections_tenant_id'), 'ai_connections', ['tenant_id'], unique=False)

    op.execute("ALTER TABLE ai_connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_connections FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ai_connections
          USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_connections")
    op.drop_index(op.f('ix_ai_connections_tenant_id'), table_name='ai_connections')
    op.drop_table('ai_connections')
