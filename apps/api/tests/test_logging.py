"""Structured logging (SRS NFR-09): request IDs that stay with their own request even when
requests overlap, tenant and job IDs when known, and secrets redacted from every line."""
import asyncio
import json
import logging

import httpx
import pytest
from fastapi import FastAPI

from app.core.logging import JSONFormatter, job_id_var, redact, tenant_id_var
from app.core.middleware import RequestIDMiddleware


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[dict[str, object]] = []
        self.setFormatter(JSONFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def capture() -> _Capture:
    handler = _Capture()
    log = logging.getLogger("test.logging")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    yield handler  # type: ignore[misc]
    log.removeHandler(handler)


def _app(delay: float = 0.0) -> FastAPI:
    api = FastAPI()
    api.add_middleware(RequestIDMiddleware)

    @api.get("/work/{name}")
    async def work(name: str) -> dict[str, str]:
        logging.getLogger("test.logging").info("start %s", name)
        await asyncio.sleep(delay)
        logging.getLogger("test.logging").info("finish %s", name)
        return {"name": name}

    return api


def _client(api: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://t")


async def test_response_echoes_a_supplied_request_id(capture: _Capture) -> None:
    async with _client(_app()) as c:
        r = await c.get("/work/a", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    assert {line["request_id"] for line in capture.lines} == {"abc-123"}


@pytest.mark.parametrize("bad", ["has space", "x" * 65, "semi;colon", "new\tline"])
async def test_unsafe_request_ids_are_replaced(capture: _Capture, bad: str) -> None:
    async with _client(_app()) as c:
        r = await c.get("/work/a", headers={"X-Request-ID": bad})
    assert r.headers["x-request-id"] != bad
    assert len(r.headers["x-request-id"]) == 36  # a fresh UUID


async def test_overlapping_requests_keep_their_own_ids(capture: _Capture) -> None:
    """The old middleware swapped a process-wide log factory, so overlapping requests
    overwrote each other's ID. Each line must carry the ID of the request that wrote it."""
    async with _client(_app(delay=0.05)) as c:
        await asyncio.gather(
            *(c.get(f"/work/n{i}", headers={"X-Request-ID": f"req-{i}"}) for i in range(20))
        )
    assert len(capture.lines) == 40
    for line in capture.lines:
        assert str(line["message"]).endswith(str(line["request_id"]).replace("req-", "n"))


async def test_ids_do_not_leak_between_requests(capture: _Capture) -> None:
    async with _client(_app()) as c:
        await c.get("/work/a", headers={"X-Request-ID": "first"})
    logging.getLogger("test.logging").info("outside any request")
    assert "request_id" not in capture.lines[-1]


def test_tenant_and_job_ids_appear_when_set(capture: _Capture) -> None:
    t1, t2 = tenant_id_var.set("tenant-1"), job_id_var.set("job-9")
    try:
        logging.getLogger("test.logging").info("indexing")
    finally:
        tenant_id_var.reset(t1)
        job_id_var.reset(t2)
    assert capture.lines[-1]["tenant_id"] == "tenant-1"
    assert capture.lines[-1]["job_id"] == "job-9"


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("calling with key sk-proj-abcdefgh12345678", "abcdefgh12345678"),
        ("anthropic sk-ant-api03-ZZZZZZZZ-yyyy", "ZZZZZZZZ"),
        ("Authorization: Bearer abc.def.ghi_JKL", "abc.def.ghi_JKL"),
        ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig-nature", "eyJhbGciOiJIUzI1NiJ9"),
        ("api_key=hunter2hunter2 extra", "hunter2hunter2"),
        ('{"password": "correct horse battery"}', "correct"),
    ],
)
def test_secrets_are_redacted(raw: str, secret: str) -> None:
    out = redact(raw)
    assert secret not in out
    assert "[redacted]" in out


def test_ordinary_text_is_untouched() -> None:
    text = "Indexed 12 passages for document 4f1c in 35 ms"
    assert redact(text) == text


def test_secrets_never_reach_the_output_even_in_tracebacks(capture: _Capture) -> None:
    log = logging.getLogger("test.logging")
    try:
        raise RuntimeError("upstream rejected key sk-live-0123456789abcdef")
    except RuntimeError:
        log.exception("provider call failed for key sk-live-0123456789abcdef")
    dumped = json.dumps(capture.lines[-1])
    assert "0123456789abcdef" not in dumped
