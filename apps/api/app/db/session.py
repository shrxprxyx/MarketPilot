import logging
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
import app.db.engine as db_engine

logger = logging.getLogger(__name__)


async def get_db():
    async with db_engine.AsyncSessionLocal() as session:
        yield session