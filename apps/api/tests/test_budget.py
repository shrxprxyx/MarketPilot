"""
Tenant monthly budget (FR-BYOM-05): spend from usage_logs, hard stop in the gateway,
and the pre-flight estimate. Provider HTTP is mocked at app.ai.providers._post_json;
the database, gateway and retrieval are real. Each test gets its own tenant so spend
never leaks between tests.
"""
import asyncio
import itertools
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.ai.gateway as gateway
import app.ai.providers as providers
import app.db.engine as db_engine
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.main import app
from app.models.membership import Membership
from app.models.usage_log import UsageLog
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)
_counter = itertools.count(1)

PLAN = {
    "summary": "Grow subscriptions.",
    "objectives": [{"title": "More", "kpis": [{"name": "Subs", "target": "10"}]}],
    "channels": [{"name": "Email", "rationale": "Retention."}],
    "risks": [{"risk": "Delay", "mitigation": "Buffer."}],
}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM tenants WHERE slug LIKE 'budgetco-%'"))
            await session.execute(text("DELETE FROM users WHERE email LIKE 'budget-%@example.com'"))
            await session.commit()

    asyncio.run(_delete())
    yield
    asyncio.run(_delete())


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway, "BACKOFF_SECONDS", 0)


@pytest.fixture
def provider_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        seen.append(body)
        return {
            "choices": [{"message": {"content": json.dumps(PLAN)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }

    monkeypatch.setattr(providers, "_post_json", fake_post)
    return seen


class Tenant:
    def __init__(self, token: str, tenant_id: UUID) -> None:
        self.token = token
        self.id = tenant_id
        self.client_id = ""


def _tenant(model: str | None = "gpt-4o-mini") -> Tenant:
    n = next(_counter)
    creds = {
        "email": f"budget-admin-{n}@example.com",
        "password": "budgetadmin1234",
        "tenant_name": f"BudgetCo {n}",
    }
    client.post("/api/v1/auth/register", json=creds)
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    token = str(r.json()["access_token"])
    me = client.get("/api/v1/me", headers=_auth(token)).json()
    t = Tenant(token, UUID(me["tenant_id"]))
    c = client.post(
        "/api/v1/clients",
        json={"name": "Budget Client", "industry": "Coffee", "goals": ["Grow"]},
        headers=_auth(token),
    )
    t.client_id = str(c.json()["id"])
    if model:
        conn = client.post(
            "/api/v1/ai/connections",
            json={"provider": "openai", "label": "b", "api_key": "sk-budget-key-1234"},
            headers=_auth(token),
        )
        body = [{"task_type": "strategy", "connection_id": conn.json()["id"], "model": model}]
        assert client.put("/api/v1/ai/routes", json=body, headers=_auth(token)).status_code == 200
    return t


async def _member_token(tenant_id: UUID) -> str:
    async with db_engine.AsyncSessionLocal() as session:
        n = next(_counter)
        user = User(
            email=f"budget-member-{n}@example.com", hashed_password=hash_password("x-irrelevant-1")
        )
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="member"))
        await session.commit()
        return create_access_token(user.id, tenant_id, "member")


async def _manager_token(tenant_id: UUID) -> str:
    async with db_engine.AsyncSessionLocal() as session:
        n = next(_counter)
        user = User(
            email=f"budget-manager-{n}@example.com", hashed_password=hash_password("x-irrelevant-1")
        )
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="manager"))
        await session.commit()
        return create_access_token(user.id, tenant_id, "manager")


def _seed(tenant_id: UUID, cost: str | None, when: datetime | None = None) -> None:
    async def _go() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await set_rls_context(session, tenant_id=tenant_id)
            session.add(
                UsageLog(
                    tenant_id=tenant_id,
                    provider="openai",
                    task_type="strategy",
                    model="gpt-4o",
                    tokens_in=1,
                    tokens_out=1,
                    cost_usd=None if cost is None else Decimal(cost),
                    latency_ms=1,
                    created_at=when or datetime.now(timezone.utc),
                )
            )
            await session.commit()

    asyncio.run(_go())


def _usage_rows(tenant_id: UUID) -> int:
    async def _go() -> int:
        async with db_engine.AsyncSessionLocal() as session:
            await set_rls_context(session, tenant_id=tenant_id)
            return int(await session.scalar(text("SELECT count(*) FROM usage_logs")) or 0)

    return asyncio.run(_go())


def _set_budget(t: Tenant, amount: float | None, hard_stop: bool = False) -> Any:
    return client.put(
        "/api/v1/ai/budget",
        json={"monthly_budget_usd": amount, "hard_stop": hard_stop},
        headers=_auth(t.token),
    )


def _budget(token: str) -> Any:
    return client.get("/api/v1/ai/budget", headers=_auth(token))


def _generate(t: Tenant) -> Any:
    return client.post(
        f"/api/v1/clients/{t.client_id}/strategies",
        json={"month": "2026-12"},
        headers=_auth(t.token),
    )


# ---------- storage and status ----------


def test_no_budget_means_no_limits(provider_calls: list[dict[str, Any]]) -> None:
    t = _tenant()
    _seed(t.id, "999.00")
    b = _budget(t.token).json()
    assert b["monthly_budget_usd"] is None and b["percent_used"] is None
    assert b["hard_stop"] is False
    assert _generate(t).status_code == 201


def test_put_and_get_budget_roundtrip() -> None:
    t = _tenant()
    _seed(t.id, "20.00")
    assert _set_budget(t, 50, hard_stop=True).status_code == 200
    b = _budget(t.token).json()
    assert Decimal(b["monthly_budget_usd"]) == Decimal("50.00")
    assert b["hard_stop"] is True
    assert Decimal(b["spent_usd"]) == Decimal("20.00")
    assert b["percent_used"] == 40
    assert b["month"] == datetime.now(timezone.utc).strftime("%Y-%m")


@pytest.mark.parametrize("amount", [0, -5])
def test_budget_validation(amount: float) -> None:
    t = _tenant()
    assert _set_budget(t, amount).status_code == 422


def test_null_clears_the_budget() -> None:
    t = _tenant()
    _set_budget(t, 10, hard_stop=True)
    assert _set_budget(t, None).status_code == 200
    assert _budget(t.token).json()["monthly_budget_usd"] is None


def test_only_admin_sets_manager_reads_member_forbidden() -> None:
    t = _tenant()
    manager = asyncio.run(_manager_token(t.id))
    member = asyncio.run(_member_token(t.id))
    put = {"monthly_budget_usd": 5, "hard_stop": False}
    assert client.put("/api/v1/ai/budget", json=put, headers=_auth(manager)).status_code == 403
    assert client.put("/api/v1/ai/budget", json=put, headers=_auth(member)).status_code == 403
    assert _budget(manager).status_code == 200
    assert _budget(member).status_code == 403


def test_spend_counts_only_this_tenant_and_this_month() -> None:
    t = _tenant()
    other = _tenant()
    _seed(t.id, "3.00")
    _seed(t.id, "100.00", when=datetime.now(timezone.utc) - timedelta(days=40))
    _seed(other.id, "50.00")
    assert Decimal(_budget(t.token).json()["spent_usd"]) == Decimal("3.00")


def test_unpriced_calls_are_counted_not_added() -> None:
    t = _tenant()
    _seed(t.id, "2.00")
    _seed(t.id, None)
    b = _budget(t.token).json()
    assert Decimal(b["spent_usd"]) == Decimal("2.00") and b["unpriced_calls"] == 1


def test_budget_changes_are_audit_logged() -> None:
    t = _tenant()
    _set_budget(t, 12, hard_stop=True)
    r = client.get("/api/v1/audit-log", headers=_auth(t.token))
    assert "ai_budget.updated" in r.text


# ---------- gateway enforcement ----------


def test_hard_stop_blocks_when_spend_reaches_budget(provider_calls: list[dict[str, Any]]) -> None:
    t = _tenant()
    _seed(t.id, "1.00")
    _set_budget(t, 1, hard_stop=True)
    rows = _usage_rows(t.id)
    r = _generate(t)
    assert r.status_code == 402, r.text
    assert "AI models" in r.json()["detail"]
    assert provider_calls == []  # the model was never called
    assert _usage_rows(t.id) == rows  # and nothing was recorded


def test_hard_stop_allows_just_below_budget(provider_calls: list[dict[str, Any]]) -> None:
    t = _tenant()
    _seed(t.id, "0.99")
    _set_budget(t, 1, hard_stop=True)
    assert _generate(t).status_code == 201


def test_over_budget_without_hard_stop_still_allowed(provider_calls: list[dict[str, Any]]) -> None:
    t = _tenant()
    _seed(t.id, "5.00")
    _set_budget(t, 1, hard_stop=False)
    assert _generate(t).status_code == 201
    assert _budget(t.token).json()["percent_used"] >= 500


def test_lowering_budget_below_spend_blocks_next_call(
    provider_calls: list[dict[str, Any]],
) -> None:
    t = _tenant()
    _seed(t.id, "2.00")
    _set_budget(t, 10, hard_stop=True)
    assert _generate(t).status_code == 201
    _set_budget(t, 1, hard_stop=True)
    assert _generate(t).status_code == 402


# ---------- unpriced models under a hard stop ----------


def _route_with_fallback(t: Tenant, model: str, fallback_model: str) -> None:
    conn = client.post(
        "/api/v1/ai/connections",
        json={"provider": "openai", "label": "fb", "api_key": "sk-fallback-key-1234"},
        headers=_auth(t.token),
    ).json()["id"]
    routes = client.get("/api/v1/ai/routes", headers=_auth(t.token)).json()
    body = [
        {
            "task_type": "strategy",
            "connection_id": routes[0]["connection_id"],
            "model": model,
            "fallback_connection_id": conn,
            "fallback_model": fallback_model,
        }
    ]
    assert client.put("/api/v1/ai/routes", json=body, headers=_auth(t.token)).status_code == 200


def test_hard_stop_refuses_an_unpriced_model(provider_calls: list[dict[str, Any]]) -> None:
    t = _tenant(model="some-unpriced-model")
    _set_budget(t, 5, hard_stop=True)
    rows = _usage_rows(t.id)
    r = _generate(t)
    assert r.status_code == 409, r.text
    assert "no known price" in r.json()["detail"]
    assert provider_calls == [] and _usage_rows(t.id) == rows  # never called, nothing recorded


def test_unpriced_model_is_allowed_without_hard_stop(
    provider_calls: list[dict[str, Any]],
) -> None:
    t = _tenant(model="some-unpriced-model")
    _set_budget(t, 5, hard_stop=False)
    assert _generate(t).status_code == 201
    assert _budget(t.token).json()["unpriced_calls"] == 1


def test_hard_stop_falls_back_to_a_priced_model(provider_calls: list[dict[str, Any]]) -> None:
    t = _tenant(model="some-unpriced-model")
    _route_with_fallback(t, "some-unpriced-model", "gpt-4o-mini")
    _set_budget(t, 5, hard_stop=True)
    r = _generate(t)
    assert r.status_code == 201, r.text
    assert r.json()["model_used"] == "gpt-4o-mini"
    assert r.json()["cost_usd"] is not None


def test_anthropic_models_are_priced() -> None:
    async def _prices() -> dict[str, tuple[Decimal, Decimal]]:
        async with db_engine.AsyncSessionLocal() as session:
            return {
                m: await gateway._price(session, "anthropic", m)  # type: ignore[misc]
                for m in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5")
            }

    prices = asyncio.run(_prices())
    assert prices["claude-sonnet-5-5"] == (Decimal("2"), Decimal("10"))
    assert prices["claude-opus-5-5"] == (Decimal("4"), Decimal("20"))
    assert prices["claude-haiku-5-5"] == (Decimal("0.1"), Decimal("0.5"))
    # 1M input + 1M output tokens on Sonnet 5.5 = $2 + $10
    cost = gateway.compute_cost(prices["claude-sonnet-5-5"], 1_000_000, 1_000_000)
    assert cost == Decimal(12)


# ---------- estimate ----------


def _estimate(token: str, client_id: str, month: str = "2026-12") -> Any:
    return client.get(
        "/api/v1/ai/usage/estimate",
        params={"task": "strategy", "client_id": client_id, "month": month},
        headers=_auth(token),
    )


def test_estimate_returns_tokens_and_max_cost_without_calling_the_model(
    provider_calls: list[dict[str, Any]],
) -> None:
    t = _tenant("gpt-4o-mini")  # 0.15 in / 0.60 out per 1M tokens
    r = _estimate(t.token, t.client_id)
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["tokens_in_est"] > 0 and e["tokens_out_max"] == 2048
    assert e["model"] == "gpt-4o-mini"
    expected = (
        Decimal(e["tokens_in_est"]) * Decimal("0.15")
        + Decimal(e["tokens_out_max"]) * Decimal("0.60")
    ) / Decimal(1_000_000)
    assert Decimal(e["cost_max_usd"]) == expected.quantize(Decimal("0.000001"))
    assert provider_calls == []


def test_estimate_unpriced_model_has_null_cost() -> None:
    t = _tenant("mystery-model")
    assert _estimate(t.token, t.client_id).json()["cost_max_usd"] is None


def test_estimate_without_route_returns_409() -> None:
    t = _tenant(model=None)
    r = _estimate(t.token, t.client_id)
    assert r.status_code == 409 and "AI models" in r.json()["detail"]


def test_estimate_member_forbidden_and_other_tenant_404() -> None:
    t = _tenant()
    other = _tenant()
    member = asyncio.run(_member_token(t.id))
    assert _estimate(member, t.client_id).status_code == 403
    assert _estimate(other.token, t.client_id).status_code == 404
