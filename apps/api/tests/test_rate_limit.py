"""Per-user and per-tenant rate limits (SRS §8): 429 with Retry-After once a budget is
spent, counted separately per tenant, and the limiter fails open if Redis is down."""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.core.rate_limit as rl
from app.auth.dependencies import CurrentUser, get_current_user
from app.core.errors import ProblemException, problem_exception_handler
from app.core.redis import get_redis


@pytest.fixture(autouse=True)
def _real_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rl.settings, "rate_limit_scale", 1.0)


class _U:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


def _app(current: CurrentUser, **limits: int) -> TestClient:
    api = FastAPI()
    api.add_exception_handler(ProblemException, problem_exception_handler)
    api.dependency_overrides[get_current_user] = lambda: current

    @api.post("/x", dependencies=[rl.rate_limit(f"test-{uuid.uuid4()}", **limits)])
    async def _x() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(api)


def _current(tenant_id: uuid.UUID | None = None, user: _U | None = None) -> CurrentUser:
    return CurrentUser(user=user or _U(), tenant_id=tenant_id or uuid.uuid4(), role="admin")  # type: ignore[arg-type]


def test_user_limit_returns_429_with_retry_after() -> None:
    c = _app(_current(), user=2, tenant=100)
    assert c.post("/x").status_code == 200
    assert c.post("/x").status_code == 200
    r = c.post("/x")
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert "user" in r.json()["detail"]


def test_tenant_limit_is_shared_across_users() -> None:
    tenant = uuid.uuid4()
    name = f"test-{uuid.uuid4()}"
    api = FastAPI()
    api.add_exception_handler(ProblemException, problem_exception_handler)
    current = {"v": _current(tenant)}
    api.dependency_overrides[get_current_user] = lambda: current["v"]

    @api.post("/x", dependencies=[rl.rate_limit(name, user=100, tenant=2)])
    async def _x() -> dict[str, bool]:
        return {"ok": True}

    c = TestClient(api)
    assert c.post("/x").status_code == 200
    current["v"] = _current(tenant)  # a different user, same agency
    assert c.post("/x").status_code == 200
    r = c.post("/x")
    assert r.status_code == 429
    assert "agency" in r.json()["detail"]


def test_other_tenants_are_not_affected() -> None:
    name = f"test-{uuid.uuid4()}"
    api = FastAPI()
    api.add_exception_handler(ProblemException, problem_exception_handler)
    current = {"v": _current()}
    api.dependency_overrides[get_current_user] = lambda: current["v"]

    @api.post("/x", dependencies=[rl.rate_limit(name, user=1, tenant=1)])
    async def _x() -> dict[str, bool]:
        return {"ok": True}

    c = TestClient(api)
    assert c.post("/x").status_code == 200
    assert c.post("/x").status_code == 429
    current["v"] = _current()
    assert c.post("/x").status_code == 200


def test_fails_open_when_redis_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(key: str, window: int) -> tuple[int, int]:
        raise ConnectionError("redis down")

    monkeypatch.setattr(rl, "_hit", boom)
    c = _app(_current(), user=1, tenant=1)
    assert c.post("/x").status_code == 200
    assert c.post("/x").status_code == 200


def test_key_expiry_is_repaired(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def run() -> int:
        r = get_redis()
        key = f"rl:test-ttl:{uuid.uuid4()}"
        await r.set(key, "5")  # a counter that lost its expiry
        count, retry = await rl._hit(key, 60)
        ttl = int(await r.ttl(key))
        await r.delete(key)
        assert count == 6 and retry == 60
        return ttl

    assert asyncio.run(run()) > 0
