"""Structured JSON logging (SRS NFR-09): every line carries the request ID, and the tenant ID
and job ID when known, and secrets are redacted before anything is written.

The IDs live in context variables, so concurrent requests (and concurrent tasks) each see
their own values. They are set by RequestIDMiddleware, by the auth dependency once the tenant
is known, and by the worker when it starts a job.
"""
import json
import logging
import re
import sys
from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)

# Provider API keys (OpenAI "sk-...", Anthropic "sk-ant-..."), bearer tokens, JWTs and
# key=value style secrets. Applied to the message and to formatted tracebacks.
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]+=*"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|password|token|authorization)(\"?\s*[:=]\s*\"?)[^\s\"',;}&]+"
    ),
)


def redact(text: str) -> str:
    text = _SECRET_PATTERNS[0].sub("[redacted]", text)
    text = _SECRET_PATTERNS[1].sub("Bearer [redacted]", text)
    text = _SECRET_PATTERNS[2].sub("[redacted]", text)
    return _SECRET_PATTERNS[3].sub(r"\1\2[redacted]", text)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key, var in (
            ("request_id", request_id_var),
            ("tenant_id", tenant_id_var),
            ("job_id", job_id_var),
        ):
            value = getattr(record, key, None) or var.get()
            if value:
                log[key] = value
        if record.exc_info:
            log["exc_info"] = redact(self.formatException(record.exc_info))
        return json.dumps(log)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
