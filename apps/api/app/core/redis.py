import asyncio

from redis import asyncio as aioredis

from app.config import settings

_redis: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def get_redis() -> aioredis.Redis:
    """Async Redis client, cached per event loop.

    One loop lives for the whole process in production (uvicorn), so this caches a
    single connection pool there. Test clients that spin up a fresh event loop per
    call would otherwise reuse a connection bound to an already-closed loop, so a
    loop change forces a fresh client instead.
    """
    global _redis, _redis_loop
    loop = asyncio.get_event_loop()
    if _redis is None or _redis_loop is not loop:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        _redis_loop = loop
    return _redis
