"""app_user role and RLS policy on memberships

Revision ID: 126facb9e740
Revises: 17ee337cd36c
Create Date: 2026-11-18 18:44:32.215629

"""
from collections.abc import Sequence

from alembic import op
from app.config import settings

# revision identifiers, used by Alembic.
revision: str = '126facb9e740'
down_revision: str | Sequence[str] | None = '17ee337cd36c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the non-owner, non-superuser role the API connects as, and turn on
    RLS for memberships. Table owners and superusers always bypass RLS (even with
    FORCE ROW LEVEL SECURITY), which is why the runtime API must NOT connect as the
    migration/owner role (`marketpilot`) once this lands.
    """
    escaped_password = settings.app_user_db_password.replace("'", "''")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
                CREATE ROLE app_user;
            END IF;
        END $$;
        """
    )
    op.execute(
        f"ALTER ROLE app_user WITH LOGIN PASSWORD '{escaped_password}' "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
    )

    op.execute("DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO app_user', current_database()); END $$;")
    op.execute("GRANT USAGE ON SCHEMA public TO app_user")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_user"
    )

    # `memberships` bridges global users to tenants. Reads may match on EITHER the
    # current tenant_id or the current user_id, because register/login need to
    # resolve a user's own memberships before a tenant has been chosen. Writes are
    # deliberately NOT given that user_id escape hatch — if they were, a caller
    # scoped only to their own user_id could insert/update a membership row under
    # any tenant_id. Every future table keyed only on tenant_id should use a plain
    # tenant_id-only policy — do not copy the SELECT OR-clause onto them.
    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY memberships_select ON memberships
          FOR SELECT
          USING (
            tenant_id = current_setting('app.tenant_id', true)::uuid
            OR user_id = current_setting('app.user_id', true)::uuid
          )
        """
    )
    op.execute(
        """
        CREATE POLICY memberships_insert ON memberships
          FOR INSERT
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY memberships_update ON memberships
          FOR UPDATE
          USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY memberships_delete ON memberships
          FOR DELETE
          USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS memberships_select ON memberships")
    op.execute("DROP POLICY IF EXISTS memberships_insert ON memberships")
    op.execute("DROP POLICY IF EXISTS memberships_update ON memberships")
    op.execute("DROP POLICY IF EXISTS memberships_delete ON memberships")
    op.execute("ALTER TABLE memberships NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships DISABLE ROW LEVEL SECURITY")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_user"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM app_user"
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_user")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM app_user")
    op.execute("REVOKE USAGE ON SCHEMA public FROM app_user")
    op.execute(
        "DO $$ BEGIN EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM app_user', current_database()); END $$;"
    )
    op.execute("ALTER ROLE app_user WITH NOLOGIN")
