import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: any) -> Response:  # type: ignore[override]
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        # attach to all log records for this request
        old_factory = logging.getLogRecordFactory()

        def record_factory(*args: any, **kwargs: any) -> logging.LogRecord:  # type: ignore[misc]
            record = old_factory(*args, **kwargs)
            record.request_id = request_id  # type: ignore[attr-defined]
            return record

        logging.setLogRecordFactory(record_factory)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logging.setLogRecordFactory(old_factory)
        return response