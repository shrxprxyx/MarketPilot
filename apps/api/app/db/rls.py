from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_rls_context(
    session: AsyncSession,
    *,
    tenant_id: UUID | str | None = None,
    user_id: UUID | str | None = None,
    invite_token_hash: str | None = None,
) -> None:
    """Set the Postgres session variables RLS policies read, scoped to the current
    transaction (set_config(..., is_local=true) resets when the transaction ends).

    `memberships` is the bridge table between global identity (users) and tenant
    scope, so its policy allows a row through on EITHER the current tenant_id or the
    current user_id — that's what lets a user look up their own memberships before
    a tenant has been chosen (register/login). `invites` has the same problem for
    accept-invite (no tenant_id OR user_id is known yet — the invitee may not even
    have a user row), so its SELECT/DELETE policies add a third branch keyed on the
    exact token hash the caller already proved possession of. Every other
    tenant-scoped table is keyed on tenant_id alone and gets no such escape hatch.

    Policies MUST read these settings as
    `NULLIF(current_setting('app.tenant_id', true), '')::uuid`, never a bare
    `current_setting(...)::uuid`: after a pooled connection has set a variable once,
    later transactions see '' instead of NULL, and the bare cast then raises
    (migration d4f7b1c8a2e6, tests/isolation/test_pooled_connection.py).
    """
    # One statement for however many variables are set: this runs on every request, and each
    # extra round trip to Postgres is paid by every endpoint.
    settings = {
        "app.tenant_id": str(tenant_id) if tenant_id is not None else None,
        "app.user_id": str(user_id) if user_id is not None else None,
        "app.invite_token_hash": invite_token_hash,
    }
    chosen = [(name, value) for name, value in settings.items() if value is not None]
    if not chosen:
        return
    calls = ", ".join(f"set_config(:k{i}, :v{i}, true)" for i in range(len(chosen)))
    params: dict[str, str] = {}
    for i, (name, value) in enumerate(chosen):
        params[f"k{i}"] = name
        params[f"v{i}"] = str(value)
    await session.execute(text(f"SELECT {calls}"), params)  # noqa: S608 - names are fixed above
