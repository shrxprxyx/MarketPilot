import logging

import asyncpg
from fastapi import APIRouter
from redis import asyncio as aioredis

from app.config import settings
from app.core.errors import problem

router = APIRouter(tags=["platform"])
logger = logging.getLogger(__name__)


@router.get("/ready")
async def ready() -> dict[str, str]:
    # check Postgres
    try:
        conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
        await conn.execute("SELECT 1")
        await conn.close()
    except Exception as exc:
        logger.warning("Postgres not ready: %s", exc)
        return problem(503, "Service Unavailable", "Postgres is not reachable.")  # type: ignore[return-value]

    # check Redis
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
    except Exception as exc:
        logger.warning("Redis not ready: %s", exc)
        return problem(503, "Service Unavailable", "Redis is not reachable.")  # type: ignore[return-value]

    return {"status": "ok"}