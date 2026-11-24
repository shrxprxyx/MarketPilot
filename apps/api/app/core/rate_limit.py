"""Per-user and per-tenant rate limits for expensive endpoints (SRS §8, §11).

A fixed-window counter in Redis, so the limit holds across API processes. Each protected
route declares its own budget:

    @router.post(..., dependencies=[rate_limit("strategy.generate", user=10, tenant=30)])

Counters are keyed by the tenant and user from the verified token, never by anything the
client sends. If Redis is unreachable the request is allowed (and logged): a cache outage
should not take generation or uploads down with it. Login brute force is a separate,
stricter mechanism (app.auth.rate_limit) and still fails closed.
"""
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends

from app.auth.dependencies import CurrentUser, get_current_user
from app.config import settings
from app.core.errors import ProblemException
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_SECONDS = 60


async def _hit(key: str, window: int) -> tuple[int, int]:
    """Increment `key`; returns (count in this window, seconds until the window resets)."""
    r = get_redis()
    count = int(await r.incr(key))
    if count == 1:
        await r.expire(key, window)
        return count, window
    ttl = int(await r.ttl(key))
    if ttl < 0:  # key lost its expiry (crash between INCR and EXPIRE): repair it
        await r.expire(key, window)
        ttl = window
    return count, ttl


def rate_limit(
    name: str, *, user: int, tenant: int, window: int = DEFAULT_WINDOW_SECONDS
) -> Any:
    """Dependency enforcing `user` requests per user and `tenant` per tenant per window."""

    async def _check(current: Annotated[CurrentUser, Depends(get_current_user)]) -> None:
        checks = (
            (f"rl:{name}:t:{current.tenant_id}", tenant, "agency"),
            (f"rl:{name}:u:{current.tenant_id}:{current.user.id}", user, "user"),
        )
        for key, limit, who in checks:
            try:
                count, retry_after = await _hit(key, window)
            except Exception:
                logger.warning("Rate limiter unavailable; allowing %s", name, exc_info=True)
                return
            if count > max(1, round(limit * settings.rate_limit_scale)):
                raise ProblemException(
                    429,
                    "Too Many Requests",
                    f"Rate limit reached for this {who}. Try again in {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)},
                )

    checker: Callable[..., Awaitable[None]] = _check
    return Depends(checker)
