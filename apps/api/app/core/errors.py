import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ProblemException(Exception):
    """Raised inside route handlers to return an RFC 7807 problem+json response."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        self.status = status
        self.title = title
        self.detail = detail
        self.headers = headers
        self.extra = extra
        super().__init__(detail)


def problem(
    status: int,
    title: str,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    """Return an RFC 7807 problem+json response (use in exception handlers)."""
    body: dict[str, Any] = {"status": status, "title": title, "detail": detail}
    body.update(extra)
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
        headers=headers,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return problem(500, "Internal Server Error", "An unexpected error occurred.")


async def problem_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemException)
    return problem(exc.status, exc.title, exc.detail, headers=exc.headers, **exc.extra)
