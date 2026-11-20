"""
RLS policies must survive a reused (pooled) database connection.

`set_config('app.tenant_id', ..., true)` is transaction-local, but once a
connection has ever set it, Postgres keeps the setting registered and reports it
as an EMPTY STRING (not NULL) in later transactions. A policy that casts
`current_setting('app.tenant_id', true)::uuid` then raises
`invalid input syntax for type uuid: ""` on any later transaction that did not
set that variable again, e.g. login, which only knows the user_id.

The test suite normally uses NullPool (tests/conftest.py), where every
transaction gets a brand-new connection, so it never saw this. These tests use a
real pool of size one so the same physical connection is reused, like production.
"""
from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.db.engine as db_engine
from app.auth.password import hash_password
from app.config import settings
from app.db.rls import set_rls_context
from app.models.membership import Membership
from app.models.tenant import Tenant
from app.models.user import User

_EMAIL = "pool-alice@example.com"
_SLUG = "pool-alice-co"


@pytest.fixture
async def pooled_engine() -> AsyncGenerator[AsyncEngine, None]:
    """One physical connection, reused for every transaction below."""
    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
    yield engine
    await engine.dispose()


async def _poison(engine: AsyncEngine, *, tenant: bool = True, user: bool = True) -> None:
    """Leave the pooled connection the way a finished request leaves it."""
    async with engine.begin() as conn:
        if tenant:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :v, true)"), {"v": str(uuid4())}
            )
        if user:
            await conn.execute(
                text("SELECT set_config('app.user_id', :v, true)"), {"v": str(uuid4())}
            )


async def test_every_rls_table_tolerates_a_stale_empty_setting(
    pooled_engine: AsyncEngine,
) -> None:
    async with pooled_engine.connect() as conn:
        tables = [
            r[0]
            for r in await conn.execute(
                text("SELECT DISTINCT tablename FROM pg_policies WHERE schemaname = 'public'")
            )
        ]
    assert "memberships" in tables and "clients" in tables  # sanity: policies exist

    await _poison(pooled_engine)

    for table in tables:
        async with pooled_engine.connect() as conn:
            # No context set at all: the stale '' settings must read as "no tenant",
            # i.e. default-deny with zero rows, not an exception.
            count = await conn.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
            assert count == 0, f"{table} should deny everything without RLS context"


@pytest.fixture
async def alice() -> AsyncGenerator[UUID, None]:
    async def _cleanup() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM tenants WHERE slug = :s"), {"s": _SLUG})
            await session.execute(text("DELETE FROM users WHERE email = :e"), {"e": _EMAIL})
            await session.commit()

    await _cleanup()
    async with db_engine.AsyncSessionLocal() as session:
        user = User(email=_EMAIL, hashed_password=hash_password("irrelevant-1234"))
        tenant = Tenant(name="Pool Alice Co", slug=_SLUG)
        session.add_all([user, tenant])
        await session.flush()
        await set_rls_context(session, tenant_id=tenant.id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant.id, role="admin"))
        user_id = user.id
        await session.commit()
    yield user_id
    await _cleanup()


async def test_user_only_context_finds_memberships_on_a_reused_connection(
    pooled_engine: AsyncEngine, alice: UUID
) -> None:
    """The login path: only user_id is known, after a previous request set tenant_id."""
    await _poison(pooled_engine, user=False)

    async with pooled_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.user_id', :v, true)"), {"v": str(alice)}
        )
        count = await conn.scalar(
            text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": alice}
        )
    assert count == 1
