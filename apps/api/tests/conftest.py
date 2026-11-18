# apps/api/tests/conftest.py
import asyncio
import pytest
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
import app.db.engine as db_engine
from app.config import settings


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
def cleanup_test_user(use_null_pool: None) -> None:
    """Delete the auto test user before the session starts so register always works."""

    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            try:
                await session.execute(
                    text("DELETE FROM users WHERE email = 'auto@example.com'")
                )
                await session.commit()
            except Exception:
                await session.rollback()
                # Table doesn't exist yet (fresh DB) — that's fine,
                # test_register will create the user from scratch.

    asyncio.get_event_loop().run_until_complete(_delete())