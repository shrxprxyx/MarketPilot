"""jobs table (SRS 3.5)

Revision ID: f1a5c3d7e9b2
Revises: e9f4b2a6c8d1
Create Date: 2026-11-25 02:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f1a5c3d7e9b2'
down_revision: str | Sequence[str] | None = 'e9f4b2a6c8d1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('jobs',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
    sa.Column('progress', sa.Integer(), server_default='0', nullable=False),
    sa.Column('message', sa.String(length=300), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('result_ref', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_tenant_id'), 'jobs', ['tenant_id'], unique=False)
    op.create_index('ix_jobs_tenant_created', 'jobs', ['tenant_id', 'created_at'], unique=False)
    op.create_index(
        'uq_jobs_tenant_idempotency_key', 'jobs', ['tenant_id', 'idempotency_key'], unique=True,
        postgresql_where=sa.text('idempotency_key IS NOT NULL'),
    )

    # Same tenant-only policy as every other tenant table, with the NULLIF guard that
    # migration d4f7b1c8a2e6 rolled out (a pooled connection can leave '' behind).
    op.execute("ALTER TABLE jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON jobs
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
          WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON jobs")
    op.drop_index('uq_jobs_tenant_idempotency_key', table_name='jobs', postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.drop_index('ix_jobs_tenant_created', table_name='jobs')
    op.drop_index(op.f('ix_jobs_tenant_id'), table_name='jobs')
    op.drop_table('jobs')
