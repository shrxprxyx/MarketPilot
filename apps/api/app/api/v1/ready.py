import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from redis import asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import problem
from app.db.session import get_db

router = APIRouter(tags=["platform"])
logger = logging.getLogger(__name__)

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/ready")
async def ready(db: DB) -> dict[str, str]:
    # check Postgres
    try:
        await db.execute(text("SELECT 1"))
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