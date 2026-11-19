"""task_model_routes, model_pricing, usage_logs

Revision ID: b2d5f8a1c3e4
Revises: a1c4e7d90b21
Create Date: 2026-11-19 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b2d5f8a1c3e4'
down_revision: str | Sequence[str] | None = 'a1c4e7d90b21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:  # type: ignore[type-arg]
    return (
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def upgrade() -> None:
    op.create_table('task_model_routes',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('task_type', sa.String(length=30), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('temperature', sa.Float(), server_default='0.7', nullable=False),
    sa.Column('max_tokens', sa.Integer(), server_default='2048', nullable=False),
    sa.Column('fallback_connection_id', sa.UUID(), nullable=True),
    sa.Column('fallback_model', sa.String(length=200), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    *_timestamps(),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['connection_id'], ['ai_connections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['fallback_connection_id'], ['ai_connections.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'task_type', name='uq_route_tenant_task')
    )
    op.create_index(op.f('ix_task_model_routes_tenant_id'), 'task_model_routes', ['tenant_id'], unique=False)

    op.create_table('model_pricing',
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('input_per_mtok', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('output_per_mtok', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    *_timestamps(),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'model', name='uq_pricing_provider_model')
    )

    op.create_table('usage_logs',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=True),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('task_type', sa.String(length=30), nullable=False),
    sa.Column('client_id', sa.UUID(), nullable=True),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('tokens_in', sa.Integer(), nullable=False),
    sa.Column('tokens_out', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    *_timestamps(),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['connection_id'], ['ai_connections.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_logs_tenant_id'), 'usage_logs', ['tenant_id'], unique=False)

    # Only prices that are well known; extend this table as needed. Unpriced
    # models get cost_usd NULL rather than a guessed number.
    op.execute(
        "INSERT INTO model_pricing (id, provider, model, input_per_mtok, output_per_mtok) VALUES "
        "(gen_random_uuid(), 'openai', 'gpt-4o', 2.50, 10.00), "
        "(gen_random_uuid(), 'openai', 'gpt-4o-mini', 0.15, 0.60)"
    )

    for table in ("task_model_routes", "usage_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
              WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )


def downgrade() -> None:
    for table in ("task_model_routes", "usage_logs"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index(op.f('ix_usage_logs_tenant_id'), table_name='usage_logs')
    op.drop_table('usage_logs')
    op.drop_table('model_pricing')
    op.drop_index(op.f('ix_task_model_routes_tenant_id'), table_name='task_model_routes')
    op.drop_table('task_model_routes')
