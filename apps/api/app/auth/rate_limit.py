"""Login brute-force protection (FR-AUTH-03): 5 attempts per minute per IP+email,
with a temporary lockout once the limit is hit. Backed by Redis so it holds across
multiple API processes.
"""

from app.core.errors import ProblemException
from app.core.redis import get_redis

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60
LOCKOUT_SECONDS = 60


def _attempts_key(email: str, ip: str) -> str:
    return f"login_attempts:{email}:{ip}"


def _lockout_key(email: str, ip: str) -> str:
    return f"login_lockout:{email}:{ip}"


async def enforce_login_rate_limit(email: str, ip: str) -> None:
    """Raise 429 if this email+IP pair is currently locked out."""
    if await get_redis().get(_lockout_key(email, ip)):
        raise ProblemException(
            429,
            "Too Many Requests",
            "Too many failed login attempts. Try again in a minute.",
        )


async def record_login_failure(email: str, ip: str) -> None:
    r = get_redis()
    key = _attempts_key(email, ip)
    attempts = await r.incr(key)
    if attempts == 1:
        await r.expire(key, WINDOW_SECONDS)
    if attempts >= MAX_ATTEMPTS:
        await r.set(_lockout_key(email, ip), "1", ex=LOCKOUT_SECONDS)


async def clear_login_attempts(email: str, ip: str) -> None:
    r = get_redis()
    await r.delete(_attempts_key(email, ip), _lockout_key(email, ip))
