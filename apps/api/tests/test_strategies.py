"""
Strategy slice (FR-RAG-05, FR-STR-01/04/07): generation through the AI gateway with
retrieved sources and cost. Provider HTTP is mocked at app.ai.providers._post_json;
retrieval/embeddings, the gateway, pricing and the database are real.
"""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.ai.gateway as gateway
import app.ai.providers as providers
import app.api.v1.knowledge as knowledge_api
import app.core.idempotency as idempotency
import app.db.engine as db_engine
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.main import app
from app.models.membership import Membership
from app.models.user import User
from app.rag.ingest import ingest_document

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {
    "email": "strat-admin@example.com",
    "password": "stratadmin1234",
    "tenant_name": "Strat Co",
}
_OTHER = {
    "email": "strat-other@example.com",
    "password": "stratother1234",
    "tenant_name": "Other Strat Co",
}

COFFEE = (
    "Our espresso blends are roasted in small batches and shipped within two days. "
    "Subscribers get fresh whole bean coffee every week with free delivery."
)

PLAN = {
    "summary": "Grow subscriptions through local SEO and email.",
    "objectives": [
        {"title": "More subscribers", "kpis": [{"name": "New subscribers", "target": "200"}]}
    ],
    "channels": [{"name": "Email", "rationale": "Highest retention."}],
    "risks": [{"risk": "Supply delays", "mitigation": "Buffer stock."}],
}


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
            email="strat-member@example.com", hashed_password=hash_password("x-irrelevant-1")
        )
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="member"))
        await session.commit()
        return create_access_token(user.id, tenant_id, "member")


def _reply(content: str, tin: int = 1000, tout: int = 500) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": tin, "completion_tokens": tout},
    }


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE slug IN ('strat-co', 'other-strat-co')")
            )
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN ('strat-admin@example.com', "
                    "'strat-other@example.com', 'strat-member@example.com')"
                )
            )
            await session.commit()

    asyncio.run(_delete())


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway, "BACKOFF_SECONDS", 0)


@pytest.fixture(scope="module")
def admin_token() -> str:
    return str(_register(_ADMIN)["access_token"])


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    return UUID(client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_id"])


def _set_route(token: str, model: str = "gpt-4o-mini") -> None:
    r = client.post(
        "/api/v1/ai/connections",
        json={"provider": "openai", "label": "strat", "api_key": "sk-strategy-key-1234"},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    body = [{"task_type": "strategy", "connection_id": r.json()["id"], "model": model}]
    assert client.put("/api/v1/ai/routes", json=body, headers=_auth(token)).status_code == 200


@pytest.fixture(scope="module")
def routed(admin_token: str) -> None:
    _set_route(admin_token)


def _new_client(token: str, **extra: Any) -> str:
    body = {"name": "Brew Co", "industry": "Coffee", "goals": ["Grow subscriptions"]} | extra
    r = client.post("/api/v1/clients", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _index_doc(token: str, cid: str, title: str = "Coffee page", body: str = COFFEE) -> str:
    jobs: list[tuple[UUID, UUID]] = []
    mp = pytest.MonkeyPatch()
    mp.setattr(knowledge_api, "enqueue_ingest", lambda t, d, job_id=None: jobs.append((t, d)))
    try:
        r = client.post(
            f"/api/v1/clients/{cid}/documents",
            json={"title": title, "text": body},
            headers=_auth(token),
        )
        assert r.status_code == 202, r.text
    finally:
        mp.undo()

    async def _go() -> None:
        for tenant, doc in jobs:
            async with db_engine.AsyncSessionLocal() as session:
                await ingest_document(session, tenant, doc)

    asyncio.run(_go())
    return str(r.json()["id"])


@pytest.fixture(scope="module")
def ready_client(admin_token: str, routed: None) -> str:
    cid = _new_client(admin_token)
    client.put(
        f"/api/v1/clients/{cid}/brand-profile",
        json={
            "voice": "Warm and cheeky",
            "tone": "Friendly",
            "audience": "Home baristas",
            "keywords": ["espresso"],
            "do_rules": ["Mention free delivery"],
            "dont_rules": ["Never discount"],
            "sample_text": None,
        },
        headers=_auth(admin_token),
    )
    _index_doc(admin_token, cid)
    return cid


def _generate(token: str, cid: str, month: str = "2026-12") -> Any:
    return client.post(
        f"/api/v1/clients/{cid}/strategies", json={"month": month}, headers=_auth(token)
    )


@pytest.fixture
def mock_model(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Returns a valid plan; the list collects every request body sent to the provider."""
    seen: list[dict[str, Any]] = []

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        seen.append(body)
        return _reply(json.dumps(PLAN), tin=1_000_000, tout=1_000_000)

    monkeypatch.setattr(providers, "_post_json", fake_post)
    return seen


# ---------- generation ----------


def test_generate_stores_plan_sources_and_cost(
    admin_token: str, ready_client: str, tenant_id: UUID, mock_model: list[dict[str, Any]]
) -> None:
    r = _generate(admin_token, ready_client)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["month"] == "2026-12" and s["version"] == 1 and s["status"] == "draft"
    assert s["plan"]["summary"] == PLAN["summary"]
    assert s["model_used"] == "gpt-4o-mini" and s["provider"] == "openai"
    assert (s["tokens_in"], s["tokens_out"]) == (1_000_000, 1_000_000)
    assert Decimal(s["cost_usd"]) == Decimal("0.75")  # 0.15 in + 0.60 out per 1M tokens
    assert s["sources"] and s["sources"][0]["document_title"] == "Coffee page"
    assert "espresso" in s["sources"][0]["excerpt"]

    async def _usage() -> int:
        async with db_engine.AsyncSessionLocal() as session:
            await set_rls_context(session, tenant_id=tenant_id)
            return int(
                await session.scalar(
                    text(
                        "SELECT count(*) FROM usage_logs WHERE task_type = 'strategy' "
                        "AND client_id = CAST(:c AS uuid)"
                    ),
                    {"c": ready_client},
                )
                or 0
            )

    assert asyncio.run(_usage()) >= 1
    detail = client.get(f"/api/v1/strategies/{s['id']}", headers=_auth(admin_token))
    assert detail.status_code == 200 and detail.json()["id"] == s["id"]


def test_prompt_contains_brand_profile_goals_and_delimited_chunks(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]]
) -> None:
    assert _generate(admin_token, ready_client, "2027-01").status_code == 201
    messages = mock_model[-1]["messages"]
    assert messages[0]["role"] == "system"
    prompt = "\n".join(m["content"] for m in messages)
    assert "Warm and cheeky" in prompt and "Grow subscriptions" in prompt
    assert "Coffee" in prompt and "2027-01" in prompt
    assert "<source" in prompt and "espresso blends are roasted" in prompt


def test_zero_chunks_still_generates_with_empty_sources(
    admin_token: str, routed: None, mock_model: list[dict[str, Any]]
) -> None:
    cid = _new_client(admin_token, name="Empty Co")
    r = _generate(admin_token, cid)
    assert r.status_code == 201, r.text
    assert r.json()["sources"] == []


def test_regenerating_same_month_creates_next_version(
    admin_token: str, routed: None, mock_model: list[dict[str, Any]]
) -> None:
    cid = _new_client(admin_token, name="Regen Co")
    assert _generate(admin_token, cid).json()["version"] == 1
    assert _generate(admin_token, cid).json()["version"] == 2
    assert _generate(admin_token, cid, "2027-02").json()["version"] == 1
    url = f"/api/v1/clients/{cid}/strategies"
    listing = client.get(url, headers=_auth(admin_token)).json()["items"]
    assert [(s["month"], s["version"]) for s in listing] == [
        ("2027-02", 1),
        ("2026-12", 2),
        ("2026-12", 1),
    ]


def test_strategy_list_is_paged_by_cursor(
    admin_token: str, routed: None, mock_model: list[dict[str, Any]]
) -> None:
    cid = _new_client(admin_token, name="Paged Co")
    for month in ("2026-11", "2026-12", "2027-01"):
        assert _generate(admin_token, cid, month).status_code == 201
    url = f"/api/v1/clients/{cid}/strategies"
    first = client.get(url, params={"limit": 2}, headers=_auth(admin_token)).json()
    assert [s["month"] for s in first["items"]] == ["2027-01", "2026-12"]
    assert first["next_cursor"]
    second = client.get(
        url, params={"limit": 2, "cursor": first["next_cursor"]}, headers=_auth(admin_token)
    ).json()
    assert [s["month"] for s in second["items"]] == ["2026-11"]
    assert second["next_cursor"] is None
    bad = client.get(url, params={"cursor": "nonsense"}, headers=_auth(admin_token))
    assert bad.status_code == 400


def test_concurrent_generations_get_distinct_versions(
    admin_token: str, routed: None, mock_model: list[dict[str, Any]]
) -> None:
    cid = _new_client(admin_token, name="Race Co")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _generate(admin_token, cid), range(2)))
    assert [r.status_code for r in results] == [201, 201]
    assert {r.json()["version"] for r in results} == {1, 2}


# ---------- failures ----------


def test_invalid_model_output_returns_502_and_stores_nothing(
    admin_token: str, routed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        return _reply("this is not json")

    monkeypatch.setattr(providers, "_post_json", bad)
    cid = _new_client(admin_token, name="Bad Output Co")
    r = _generate(admin_token, cid)
    assert r.status_code == 502, r.text
    assert "schema" in r.json()["detail"].lower()
    url = f"/api/v1/clients/{cid}/strategies"
    listing = client.get(url, headers=_auth(admin_token)).json()["items"]
    assert listing == []


def test_no_route_returns_409_with_setup_hint(
    mock_model: list[dict[str, Any]],
) -> None:
    token = str(_register(_OTHER)["access_token"])  # a tenant with no routes
    cid = _new_client(token, name="No Route Co")
    r = _generate(token, cid)
    assert r.status_code == 409
    assert "AI models" in r.json()["detail"]


def test_archived_client_returns_409(
    admin_token: str, routed: None, mock_model: list[dict[str, Any]]
) -> None:
    cid = _new_client(admin_token, name="Archived Co")
    assert client.delete(f"/api/v1/clients/{cid}", headers=_auth(admin_token)).status_code == 204
    assert _generate(admin_token, cid).status_code == 409


@pytest.mark.parametrize("month", ["2026-13", "abc", "2026-1", "2026-00", ""])
def test_bad_month_returns_422(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]], month: str
) -> None:
    assert _generate(admin_token, ready_client, month).status_code == 422


def test_unpriced_model_stores_null_cost(
    admin_token: str, mock_model: list[dict[str, Any]]
) -> None:
    other = str(_register(_OTHER)["access_token"])
    _set_route(other, model="mystery-model")
    cid = _new_client(other, name="Unpriced Co")
    r = _generate(other, cid)
    assert r.status_code == 201, r.text
    assert r.json()["cost_usd"] is None


# ---------- access control ----------


def test_member_can_read_but_not_generate(
    admin_token: str, ready_client: str, tenant_id: UUID, mock_model: list[dict[str, Any]]
) -> None:
    member = asyncio.run(_member_token(tenant_id))
    assert _generate(member, ready_client).status_code == 403
    listing = client.get(f"/api/v1/clients/{ready_client}/strategies", headers=_auth(member))
    assert listing.status_code == 200 and listing.json()["items"]


def test_other_tenant_gets_404(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]]
) -> None:
    sid = client.get(
        f"/api/v1/clients/{ready_client}/strategies", headers=_auth(admin_token)
    ).json()["items"][0]["id"]
    other = str(_register(_OTHER)["access_token"])
    assert _generate(other, ready_client).status_code == 404
    listing = client.get(f"/api/v1/clients/{ready_client}/strategies", headers=_auth(other))
    assert listing.status_code == 404
    assert client.get(f"/api/v1/strategies/{sid}", headers=_auth(other)).status_code == 404


def test_sources_survive_document_deletion(
    admin_token: str, routed: None, mock_model: list[dict[str, Any]]
) -> None:
    cid = _new_client(admin_token, name="Delete Co")
    doc_id = _index_doc(admin_token, cid, title="Doomed doc")
    made = _generate(admin_token, cid).json()
    assert made["sources"][0]["document_title"] == "Doomed doc"
    deleted = client.delete(f"/api/v1/documents/{doc_id}", headers=_auth(admin_token))
    assert deleted.status_code == 204
    again = client.get(f"/api/v1/strategies/{made['id']}", headers=_auth(admin_token)).json()
    assert again["sources"] == made["sources"]


# ---------- grounding (SRS §10.4) ----------


def test_invented_figures_are_flagged_as_warnings(
    admin_token: str, ready_client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = {**PLAN, "summary": "Revenue grew 63% to $88,000 last quarter."}

    async def fake_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        return _reply(json.dumps(plan))

    monkeypatch.setattr(providers, "_post_json", fake_post)
    r = _generate(admin_token, ready_client, month="2027-01")
    assert r.status_code == 201, r.text
    warnings = r.json()["warnings"]
    assert len(warnings) == 2
    assert "63%" in warnings[0] and "$88,000" in warnings[1]

    stored = client.get(f"/api/v1/strategies/{r.json()['id']}", headers=_auth(admin_token))
    assert stored.json()["warnings"] == warnings


def test_clean_strategy_has_no_warnings(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]]
) -> None:
    r = _generate(admin_token, ready_client, month="2027-02")
    assert r.status_code == 201, r.text
    assert r.json()["warnings"] == []


# ---------- Idempotency-Key: a retry must never call (and bill) the model again ----------


def _keyed(token: str, cid: str, key: str, month: str) -> Any:
    return client.post(
        f"/api/v1/clients/{cid}/strategies",
        json={"month": month},
        headers=_auth(token) | {"Idempotency-Key": key},
    )


def _new_key() -> str:
    return f"test-{uuid4()}"  # results are remembered for a day, so keys are unique per run


def _versions(token: str, cid: str, month: str) -> list[int]:
    rows = client.get(f"/api/v1/clients/{cid}/strategies", headers=_auth(token)).json()["items"]
    return sorted(s["version"] for s in rows if s["month"] == month)


def test_retry_with_the_same_key_replays_without_calling_the_model(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]]
) -> None:
    key = _new_key()
    first = _keyed(admin_token, ready_client, key, "2027-03")
    again = _keyed(admin_token, ready_client, key, "2027-03")
    assert first.status_code == again.status_code == 201, again.text
    assert again.json()["id"] == first.json()["id"]
    assert len(mock_model) == 1
    assert _versions(admin_token, ready_client, "2027-03") == [1]


def test_a_new_key_or_no_key_still_makes_a_new_version(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]]
) -> None:
    assert _keyed(admin_token, ready_client, _new_key(), "2027-04").status_code == 201
    assert _keyed(admin_token, ready_client, _new_key(), "2027-04").status_code == 201
    assert _generate(admin_token, ready_client, month="2027-04").status_code == 201
    assert _versions(admin_token, ready_client, "2027-04") == [1, 2, 3]


def test_a_key_reused_for_another_month_is_refused(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]]
) -> None:
    key = _new_key()
    assert _keyed(admin_token, ready_client, key, "2027-05").status_code == 201
    r = _keyed(admin_token, ready_client, key, "2027-06")
    assert r.status_code == 422 and "Idempotency-Key" in r.json()["detail"]
    assert len(mock_model) == 1


def test_a_retry_while_the_first_request_is_running_is_refused(
    admin_token: str, ready_client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The likeliest double charge: the caller gives up waiting and retries."""
    key = _new_key()
    during: list[Any] = []
    calls = 0

    async def slow_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:  # while the first call is in flight, the same request arrives again
            with ThreadPoolExecutor(max_workers=1) as pool:
                during.append(
                    pool.submit(_keyed, admin_token, ready_client, key, "2027-07").result()
                )
        return _reply(json.dumps(PLAN))

    monkeypatch.setattr(providers, "_post_json", slow_post)
    first = _keyed(admin_token, ready_client, key, "2027-07")
    assert first.status_code == 201, first.text
    assert during[0].status_code == 409, during[0].text
    assert "still being generated" in during[0].json()["detail"]
    assert calls == 1


def test_a_failed_generation_frees_the_key_for_a_retry(
    admin_token: str, ready_client: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _new_key()

    async def rejected(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        raise providers.ProviderError("The provider rejected the credentials.")

    monkeypatch.setattr(providers, "_post_json", rejected)
    assert _keyed(admin_token, ready_client, key, "2027-08").status_code == 502

    async def works(url: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
        return _reply(json.dumps(PLAN))

    monkeypatch.setattr(providers, "_post_json", works)
    assert _keyed(admin_token, ready_client, key, "2027-08").status_code == 201


def test_keys_are_private_to_their_tenant(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]]
) -> None:
    key = _new_key()
    mine = _keyed(admin_token, ready_client, key, "2027-09")
    assert mine.status_code == 201
    other = str(_register(_OTHER)["access_token"])
    _set_route(other)
    theirs = _keyed(other, _new_client(other), key, "2027-09")
    assert theirs.status_code == 201, theirs.text
    assert theirs.json()["id"] != mine.json()["id"]


def test_a_malformed_key_is_rejected_before_the_model_is_called(
    admin_token: str, ready_client: str, mock_model: list[dict[str, Any]]
) -> None:
    assert _keyed(admin_token, ready_client, "short", "2027-10").status_code == 422
    assert mock_model == []


def test_when_the_key_cannot_be_reserved_nothing_is_billed(
    admin_token: str,
    ready_client: str,
    mock_model: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asked for duplicate protection that cannot be given, refuse rather than risk it."""

    def down() -> Any:
        raise ConnectionError("redis down")

    monkeypatch.setattr(idempotency, "get_redis", down)
    r = _keyed(admin_token, ready_client, _new_key(), "2027-11")
    assert r.status_code == 503, r.text
    assert mock_model == []
