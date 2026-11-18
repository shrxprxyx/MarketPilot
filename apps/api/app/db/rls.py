from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant(session: AsyncSession, tenant_id: str) -> None:
    """Set app.tenant_id for the current transaction (used by RLS policies)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )