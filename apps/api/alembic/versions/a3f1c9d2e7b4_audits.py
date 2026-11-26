"""audits and audit_findings (FR-AUD-01, 06, 08)

Revision ID: a3f1c9d2e7b4
Revises: f1a5c3d7e9b2
Create Date: 2026-11-26 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f1c9d2e7b4'
down_revision: str | Sequence[str] | None = 'f1a5c3d7e9b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("audits", "audit_findings")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audits',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('client_id', sa.UUID(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audits_tenant_id'), 'audits', ['tenant_id'], unique=False)
    op.create_index('ix_audits_client_created', 'audits', ['client_id', 'created_at'], unique=False)

    op.create_table('audit_findings',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('audit_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=60), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('url', sa.String(length=2000), nullable=True),
    sa.Column('recommendation', sa.Text(), nullable=False),
    sa.Column('metric', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_findings_tenant_id'), 'audit_findings', ['tenant_id'], unique=False)
    op.create_index('ix_audit_findings_audit_severity', 'audit_findings', ['audit_id', 'severity'], unique=False)

    # Same tenant-only policy as every other tenant table, with the NULLIF guard.
    for table in TABLES:
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
    """Downgrade schema."""
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index('ix_audit_findings_audit_severity', table_name='audit_findings')
    op.drop_index(op.f('ix_audit_findings_tenant_id'), table_name='audit_findings')
    op.drop_table('audit_findings')
    op.drop_index('ix_audits_client_created', table_name='audits')
    op.drop_index(op.f('ix_audits_tenant_id'), table_name='audits')
    op.drop_table('audits')
