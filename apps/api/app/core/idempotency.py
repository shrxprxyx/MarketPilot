"""`Idempotency-Key` for a request that does its work inline and costs money (SRS §8).

The key is reserved in Redis before the work starts, so a retry that arrives while the first
request is still running is refused instead of doing the work twice. A reservation expires on
its own, so a crashed process cannot block a key for good. (Background work records its key on
the job row instead: see app.jobs.service.)
"""
import hashlib
import json
import logging
from uuid import UUID

from app.core.errors import ProblemException
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 10 * 60  # longer than the gateway's 300 s overall deadline
RESULT_TTL_SECONDS = 24 * 60 * 60


def _name(scope: str, tenant_id: UUID, key: str) -> str:
    return f"idem:{scope}:{tenant_id}:{hashlib.sha256(key.encode()).hexdigest()}"


async def claim(scope: str, tenant_id: UUID, key: str, fingerprint: str) -> UUID | None:
    """Reserve `key`. Returns None if the caller should do the work, or the stored result's id
    if this request already succeeded. Raises 409 while it is still running, 422 if the key
    belongs to a different request, and 503 if the key cannot be checked."""
    name = _name(scope, tenant_id, key)
    try:
        redis = get_redis()
        pending = json.dumps({"fingerprint": fingerprint})
        if await redis.set(name, pending, nx=True, ex=PENDING_TTL_SECONDS):
            return None
        raw = await redis.get(name)
    except Exception as exc:
        logger.warning("Could not check an Idempotency-Key", exc_info=True)
        raise ProblemException(
            503,
            "Service Unavailable",
            "Duplicate protection is unavailable, so nothing was generated. Try again shortly.",
        ) from exc
    stored = json.loads(raw) if raw else {"fingerprint": fingerprint}
    if stored["fingerprint"] != fingerprint:
        raise ProblemException(
            422,
            "Unprocessable Entity",
            "This Idempotency-Key was already used with a different request.",
        )
    if "result" not in stored:
        raise ProblemException(
            409, "Conflict", "This request is still being generated. Try again in a moment."
        )
    return UUID(stored["result"])


async def complete(
    scope: str, tenant_id: UUID, key: str, fingerprint: str, result_id: UUID
) -> None:
    """Remember the result. The work is already saved, so a failure here only logs."""
    value = json.dumps({"fingerprint": fingerprint, "result": str(result_id)})
    try:
        await get_redis().set(_name(scope, tenant_id, key), value, ex=RESULT_TTL_SECONDS)
    except Exception:
        logger.warning("Could not store an Idempotency-Key result", exc_info=True)


async def release(scope: str, tenant_id: UUID, key: str) -> None:
    """Free the key after a failure, so the same request can be tried again."""
    try:
        await get_redis().delete(_name(scope, tenant_id, key))
    except Exception:
        logger.warning("Could not release an Idempotency-Key", exc_info=True)
