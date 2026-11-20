"""RLS policies treat an empty app.tenant_id / app.user_id as unset

Revision ID: d4f7b1c8a2e6
Revises: c3e6a9b2d5f7
Create Date: 2026-11-20 22:00:00.000000

Once a pooled connection has run set_config('app.tenant_id', ..., true), Postgres
keeps the variable registered and returns '' (not NULL) in later transactions.
`current_setting('app.tenant_id', true)::uuid` then raises
"invalid input syntax for type uuid" for any request that did not set that
variable again (for example login, which only knows the user_id).

Wrapping the setting in NULLIF(..., '') makes a stale empty value behave exactly
like an unset one: the comparison is NULL, so the row is denied (default-deny is
unchanged). Every policy that casts app.tenant_id or app.user_id is rewritten in
place with ALTER POLICY, and the migration fails if any is left behind.
"""
import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f7b1c8a2e6"
down_revision: str | Sequence[str] | None = "c3e6a9b2d5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres stores policy expressions in this normalised form (see pg_policies).
_BARE = re.compile(r"\(current_setting\('(app\.(?:tenant_id|user_id))'::text, true\)\)::uuid")
_GUARDED = re.compile(
    r"\(NULLIF\(current_setting\('(app\.(?:tenant_id|user_id))'::text, true\), ''::text\)\)::uuid"
)
_BARE_TO_GUARDED = r"(NULLIF(current_setting('\1'::text, true), ''))::uuid"
_GUARDED_TO_BARE = r"(current_setting('\1'::text, true))::uuid"


def _rewrite(pattern: re.Pattern[str], replacement: str) -> None:
    conn = op.get_bind()
    quote = conn.dialect.identifier_preparer.quote
    policies = conn.execute(
        sa.text(
            "SELECT tablename, policyname, qual, with_check "
            "FROM pg_policies WHERE schemaname = 'public'"
        )
    ).all()
    for table, policy, qual, check in policies:
        new_qual = pattern.sub(replacement, qual) if qual else qual
        new_check = pattern.sub(replacement, check) if check else check
        clauses = []
        if new_qual != qual:
            clauses.append(f"USING ({new_qual})")
        if new_check != check:
            clauses.append(f"WITH CHECK ({new_check})")
        if clauses:
            op.execute(f"ALTER POLICY {quote(policy)} ON {quote(table)} {' '.join(clauses)}")


def _assert_none_left(pattern: re.Pattern[str], what: str) -> None:
    left = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT tablename || '.' || policyname FROM pg_policies "
                "WHERE schemaname = 'public' "
                "AND (coalesce(qual, '') || ' ' || coalesce(with_check, '')) ~ :rx"
            ),
            {"rx": pattern.pattern},
        )
        .scalars()
        .all()
    )
    if left:
        raise RuntimeError(f"policies still {what}: {left}")


def upgrade() -> None:
    _rewrite(_BARE, _BARE_TO_GUARDED)
    _assert_none_left(_BARE, "cast app.tenant_id/app.user_id without NULLIF")


def downgrade() -> None:
    _rewrite(_GUARDED, _GUARDED_TO_BARE)
    _assert_none_left(_GUARDED, "guarded with NULLIF")
