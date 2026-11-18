import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def problem(
    status: int,
    title: str,
    detail: str,
    **extra: Any,
) -> JSONResponse:
    """Return an RFC 7807 problem+json response."""
    body: dict[str, Any] = {"status": status, "title": title, "detail": detail}
    body.update(extra)
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return problem(500, "Internal Server Error", "An unexpected error occurred.")