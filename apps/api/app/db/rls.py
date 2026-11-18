from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_rls_context(
    session: AsyncSession,
    *,
    tenant_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
) -> None:
    """Set the Postgres session variables RLS policies read, scoped to the current
    transaction (set_config(..., is_local=true) resets when the transaction ends).

    `memberships` is the bridge table between global identity (users) and tenant
    scope, so its policy allows a row through on EITHER the current tenant_id or the
    current user_id — that's what lets a user look up their own memberships before
    a tenant has been chosen (register/login), while every other tenant-scoped table
    is keyed on tenant_id alone and gets no such escape hatch.
    """
    if tenant_id is not None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :v, true)"),
            {"v": str(tenant_id)},
        )
    if user_id is not None:
        await session.execute(
            text("SELECT set_config('app.user_id', :v, true)"),
            {"v": str(user_id)},
        )
