"""
Per-task routing, the AI gateway and usage tracking (FR-BYOM-03, 04, 07).

Provider HTTP is mocked at app.ai.providers._post_json; the gateway, routing,
pricing and usage rows all run against the real database.
"""
import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text

import app.ai.gateway as gateway
import app.ai.providers as providers
import app.db.engine as db_engine
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.main import app
from app.models.membership import Membership
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {
    "email": "aigw-admin@example.com",
    "password": "aigwadmin1234",
    "tenant_name": "AiGw Co",
}
_OTHER = {
    "email": "aigw-other@example.com",
    "password": "aigwother1234",
    "tenant_name": "Other AiGw Co",
}


class Plan(BaseModel):
    title: str
    steps: list[str]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(creds: dict[str, str]) -> dict[str, Any]:
    client.post("/api/v1/auth/register", json=creds)
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _member_token(tenant_id: UUID) -> str:
    async with db_engine.AsyncSessionLocal() as session:
        user = User(
            email="aigw-member@example.com", hashed_password=hash_password("x-irrelevant-1")
        )
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="member"))
        await session.commit()
        return create_access_token(user.id, tenant_id, "member")


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE slug IN ('aigw-co', 'other-aigw-co')")
            )
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN ('aigw-admin@example.com', "
                    "'aigw-other@example.com', 'aigw-member@example.com')"
                )
            )
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    return str(_register(_ADMIN)["access_token"])


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    return UUID(client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_id"])


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway, "BACKOFF_SECONDS", 0)


def _conn(token: str, **overrides: Any) -> str:
    body = {"provider": "openai", "label": "gw", "api_key": "sk-gateway-key-1234"} | overrides
    r = client.post("/api/v1/ai/connections", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _route(token: str, conn_id: str, task: str = "strategy", **extra: Any) -> Any:
    body = [{"task_type": task, "connection_id": conn_id, "model": "gpt-4o-mini"} | extra]
    return client.put("/api/v1/ai/routes", json=body, headers=_auth(token))


def _run_gateway(tenant_id: UUID, **kwargs: Any) -> Any:
    async def _go() -> Any:
        async with db_engine.AsyncSessionLocal() as session:
            await set_rls_context(session, tenant_id=tenant_id)
            result = await gateway.complete(session, tenant_id=tenant_id, user_id=None, **kwargs)
            await session.commit()
            return result

    return asyncio.run(_go())


def _openai_reply(content: str, tin: int = 1000, tout: int = 500) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": tin, "completion_tokens": tout},
    }


# ---------- routes API ----------


def test_routes_upsert_and_list(admin_token: str) -> None:
    conn_id = _conn(admin_token)
    r = _route(admin_token, conn_id, temperature=0.2, max_tokens=900)
    assert r.status_code == 200, r.text
    assert r.json()[0]["temperature"] == 0.2

    again = _route(admin_token, conn_id, model="gpt-4o")  # upsert, not duplicate
    assert again.status_code == 200
    listing = client.get("/api/v1/ai/routes", headers=_auth(admin_token)).json()
    strategy = [x for x in listing if x["task_type"] == "strategy"]
    assert len(strategy) == 1 and strategy[0]["model"] == "gpt-4o"


def test_routes_validation(admin_token: str) -> None:
    conn_id = _conn(admin_token)
    assert _route(admin_token, conn_id, task="nonsense").status_code == 422
    assert _route(admin_token, conn_id, fallback_model="x").status_code == 422  # half a pair
    missing = _route(admin_token, "00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


def test_routes_rbac_and_cross_tenant(admin_token: str, tenant_id: UUID) -> None:
    member = asyncio.run(_member_token(tenant_id))
    conn_id = _conn(admin_token)
    assert _route(member, conn_id).status_code == 403
    assert client.get("/api/v1/ai/routes", headers=_auth(member)).status_code == 403
    assert client.get("/api/v1/ai/usage", headers=_auth(member)).status_code == 403

    other = str(_register(_OTHER)["access_token"])
    assert _route(other, conn_id).status_code == 404  # another tenant's connection


# ---------- gateway ----------


def test_gateway_without_route_fails_cleanly(tenant_id: UUID, admin_token: str) -> None:
    with pytest.raises(gateway.GatewayError, match="No model route"):
        _run_gateway(tenant_id, task="analysis", messages=[{"role": "user", "content": "hi"}])


def test_gateway_records_usage_with_cost(
    admin_token: str, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn_id = _conn(admin_token)
    assert _route(admin_token, conn_id, task="content", model="gpt-4o-mini").status_code == 200
    seen: dict[str, Any] = {}

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        seen.update(url=url, headers=headers, body=body)
        return _openai_reply("hello world", tin=1_000_000, tout=1_000_000)

    monkeypatch.setattr(providers, "_post_json", fake_post)
    result = _run_gateway(
        tenant_id, task="content", messages=[{"role": "user", "content": "hi"}]
    )
    assert result.text == "hello world"
    assert seen["headers"]["Authorization"] == "Bearer sk-gateway-key-1234"
    assert seen["body"]["model"] == "gpt-4o-mini"
    assert result.cost_usd == Decimal("0.75")  # 0.15 in + 0.60 out per 1M tokens

    usage = client.get(
        "/api/v1/ai/usage", params={"group_by": "task"}, headers=_auth(admin_token)
    ).json()
    row = next(u for u in usage if u["key"] == "content")
    assert row["calls"] >= 1 and row["tokens_in"] >= 1_000_000
    assert Decimal(str(row["cost_usd"])) >= Decimal("0.75")


def test_gateway_unpriced_model_has_null_cost(
    admin_token: str, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn_id = _conn(admin_token)
    _route(admin_token, conn_id, task="analysis", model="mystery-model")

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        return _openai_reply("ok")

    monkeypatch.setattr(providers, "_post_json", fake_post)
    result = _run_gateway(tenant_id, task="analysis", messages=[{"role": "user", "content": "x"}])
    assert result.cost_usd is None
    usage = client.get(
        "/api/v1/ai/usage", params={"group_by": "model"}, headers=_auth(admin_token)
    ).json()
    assert next(u for u in usage if u["key"] == "mystery-model")["unpriced_calls"] >= 1


def test_gateway_ollama_is_priced_at_zero(
    admin_token: str, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn_id = _conn(admin_token, provider="ollama", api_key=None, base_url="http://localhost:11434")
    _route(admin_token, conn_id, task="embedding_summary", model="llama3")

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        assert url.endswith("/api/chat")
        return {"message": {"content": "local"}, "prompt_eval_count": 10, "eval_count": 5}

    monkeypatch.setattr(providers, "_post_json", fake_post)
    result = _run_gateway(
        tenant_id, task="embedding_summary", messages=[{"role": "user", "content": "x"}]
    )
    assert result.cost_usd == Decimal(0) and result.tokens_in == 10


def test_gateway_retries_transient_errors(
    admin_token: str, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn_id = _conn(admin_token)
    _route(admin_token, conn_id, task="strategy")
    calls = {"n": 0}

    async def flaky(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        calls["n"] += 1
        if calls["n"] < 3:
            raise providers.TransientProviderError("HTTP 503")
        return _openai_reply("finally")

    monkeypatch.setattr(providers, "_post_json", flaky)
    result = _run_gateway(tenant_id, task="strategy", messages=[{"role": "user", "content": "x"}])
    assert result.text == "finally" and calls["n"] == 3


def test_gateway_falls_back_to_second_connection(
    admin_token: str, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _conn(admin_token, label="primary", api_key="sk-primary-key-0001")
    backup = _conn(admin_token, label="backup", api_key="sk-backup-key-0002")
    _route(
        admin_token,
        primary,
        task="strategy",
        fallback_connection_id=backup,
        fallback_model="gpt-4o",
    )

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        if headers["Authorization"].endswith("0001"):
            raise providers.ProviderError("The provider rejected the credentials.")
        return _openai_reply("from backup")

    monkeypatch.setattr(providers, "_post_json", fake_post)
    result = _run_gateway(tenant_id, task="strategy", messages=[{"role": "user", "content": "x"}])
    assert result.text == "from backup" and result.model == "gpt-4o"


def test_gateway_validates_structured_output(
    admin_token: str, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn_id = _conn(admin_token)
    _route(admin_token, conn_id, task="strategy")
    replies = iter(['{"title": 1}', '{"title": "Q1", "steps": ["a", "b"]}'])
    bodies: list[dict[str, Any]] = []

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        bodies.append(body)
        return _openai_reply(next(replies))

    monkeypatch.setattr(providers, "_post_json", fake_post)
    result = _run_gateway(
        tenant_id, task="strategy", messages=[{"role": "user", "content": "x"}], schema=Plan
    )
    assert isinstance(result.parsed, Plan) and result.parsed.steps == ["a", "b"]
    assert bodies[0]["response_format"] == {"type": "json_object"}


def test_gateway_rejects_persistently_invalid_output(
    admin_token: str, tenant_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn_id = _conn(admin_token)
    _route(admin_token, conn_id, task="strategy")

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        return _openai_reply("not json at all")

    monkeypatch.setattr(providers, "_post_json", fake_post)
    with pytest.raises(gateway.GatewayError, match="does not match the schema"):
        _run_gateway(
            tenant_id, task="strategy", messages=[{"role": "user", "content": "x"}], schema=Plan
        )


def test_anthropic_adapter_uses_forced_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        seen.update(url=url, headers=headers, body=body)
        return {
            "content": [{"type": "tool_use", "input": {"title": "T", "steps": []}}],
            "usage": {"input_tokens": 7, "output_tokens": 3},
        }

    monkeypatch.setattr(providers, "_post_json", fake_post)
    out = asyncio.run(
        providers.AnthropicAdapter().complete(
            base_url=None,
            api_key="k",
            model="m",
            messages=[
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ],
            temperature=0.1,
            max_tokens=50,
            json_schema=Plan.model_json_schema(),
        )
    )
    assert seen["body"]["system"] == "be brief"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "respond"}
    assert all(m["role"] != "system" for m in seen["body"]["messages"])
    assert Plan.model_validate_json(out.text).title == "T"
    assert (out.tokens_in, out.tokens_out) == (7, 3)


def test_usage_is_tenant_scoped(admin_token: str) -> None:
    other = str(_register(_OTHER)["access_token"])
    rows = client.get("/api/v1/ai/usage", params={"group_by": "task"}, headers=_auth(other)).json()
    assert rows == []
