"""Single-use stream tickets (SRS §11 "Streaming auth").

Browsers cannot attach an Authorization header to EventSource or WebSocket connections, and
the Next.js proxy cannot carry them, so the page asks the API (with its bearer token) for a
ticket and opens the stream with it. A ticket lives 60 seconds, works once, and is stored
hashed, so a leaked access log or URL cannot be replayed.
"""
import hashlib
import secrets
from dataclasses import dataclass
from uuid import UUID

from app.core.redis import get_redis

TTL_SECONDS = 60


@dataclass
class TicketHolder:
    user_id: UUID
    tenant_id: UUID


def _key(ticket: str) -> str:
    return "stream_ticket:" + hashlib.sha256(ticket.encode()).hexdigest()


async def issue_ticket(user_id: UUID, tenant_id: UUID) -> str:
    ticket = secrets.token_urlsafe(32)
    await get_redis().set(_key(ticket), f"{user_id}:{tenant_id}", ex=TTL_SECONDS)
    return ticket


async def redeem_ticket(ticket: str) -> TicketHolder | None:
    """Returns who the ticket was issued to and destroys it, or None if it is unknown,
    expired or already used."""
    raw = await get_redis().getdel(_key(ticket))
    if not raw:
        return None
    try:
        user, tenant = str(raw).split(":", 1)
        return TicketHolder(UUID(user), UUID(tenant))
    except ValueError:
        return None
