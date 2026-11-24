# apps/api/tests/conftest.py
import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.db.engine as db_engine
from app.config import settings

# All test emails AND their tenant slugs (derived: lowercase, spaces→dashes)
_TEST_EMAILS_SQL = "'auto@example.com','alice@example.com','bob@example.com'"
_TEST_SLUGS_SQL  = "'auto-corp','alice-corp','bob-corp'"


@pytest.fixture(scope="session", autouse=True)
def use_null_pool() -> None:
    test_engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=False,
    )
    db_engine.engine = test_engine
    db_engine.AsyncSessionLocal = async_sessionmaker(
        test_engine, expire_on_commit=False
    )


@pytest.fixture(scope="session", autouse=True)
def relax_rate_limits() -> None:
    """Tests share a handful of tenants and call expensive endpoints in bursts; the real
    limits are exercised in test_rate_limit.py, which pins the scale back to 1."""
    settings.rate_limit_scale = 1000.0


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data(use_null_pool: None) -> None:
    """
    Wipe test rows before the session so every run starts clean.
    Delete tenants by slug directly — no JOIN, no dependency on users existing.
    Users delete via CASCADE into memberships + refresh_tokens.
    """

    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            try:
                # Delete tenants by known slug (cascades memberships)
                await session.execute(
                    text(f"DELETE FROM tenants WHERE slug IN ({_TEST_SLUGS_SQL})")
                )
                # Delete users (cascades memberships + refresh_tokens)
                await session.execute(
                    text(f"DELETE FROM users WHERE email IN ({_TEST_EMAILS_SQL})")
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                # Tables may not exist yet on a fresh DB — that's fine.
                print(f"[conftest] cleanup skipped: {exc}")

    asyncio.get_event_loop().run_until_complete(_delete())
