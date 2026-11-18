import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import problem
from app.core.redis import get_redis
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
        await get_redis().ping()
    except Exception as exc:
        logger.warning("Redis not ready: %s", exc)
        return problem(503, "Service Unavailable", "Redis is not reachable.")  # type: ignore[return-value]

    return {"status": "ok"}