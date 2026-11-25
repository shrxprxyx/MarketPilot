import ipaddress

from fastapi import Request

from app.config import settings


def client_ip(request: Request) -> str:
    if settings.trust_forwarded_for:
        # The proxy appends the address it saw, so the last entry is the one it vouches for.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass  # missing or malformed: fall back to the connection's address
    return request.client.host if request.client else "unknown"
