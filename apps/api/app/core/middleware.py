import re
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var, tenant_id_var

# A caller-supplied ID is kept only if it is short and plain; anything else gets a fresh one.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


class RequestIDMiddleware:
    """Gives every request an ID (the caller's X-Request-ID if it is well formed), exposes it to
    log records through a context variable, and echoes it in the response.

    Written as plain ASGI rather than BaseHTTPMiddleware: it adds no per-request task or
    stream wrapping, which matters on the hot path, and it never touches process-wide logging
    state, so concurrent requests cannot overwrite each other's ID.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        supplied = MutableHeaders(scope=scope).get("x-request-id")
        request_id = supplied if supplied and _SAFE_ID.match(supplied) else str(uuid.uuid4())
        id_token = request_id_var.set(request_id)
        tenant_token = tenant_id_var.set(None)  # filled in once the caller is authenticated

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(id_token)
            tenant_id_var.reset(tenant_token)
