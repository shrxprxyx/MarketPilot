"""Social accounts, export import with preview, and deterministic metrics (FR-AUD-09, 10)."""
import asyncio
import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.db.engine as db_engine
from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.main import app
from app.models.membership import Membership
from app.models.user import User
from app.social.importer import ImportFileError, parse_export
from app.social.metrics import compute_metrics

client = TestClient(app, raise_server_exceptions=False)

_ADMIN = {"email": "soc-admin@example.com", "password": "socadmin12345", "tenant_name": "Soc Co"}
_OTHER = {"email": "soc-other@example.com", "password": "socother12345", "tenant_name": "Soc Two"}

FB_CSV = (
    "Post ID,Publish time,Post type,Post message,Impressions,Reach,Reactions,Comments,Shares,"
    "Link clicks\n"
    "p1,2026-11-02 09:00:00,Photo,Launch day,1000,800,50,5,5,10\n"  # Monday
    "p2,2026-11-03 18:00:00,Video,Behind the scenes,2000,1500,100,20,10,20\n"  # Tuesday
    "p3,2026-11-09 09:00:00,Photo,Weekly tip,500,400,5,0,0,0\n"  # Monday
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(creds: dict[str, str]) -> str:
    client.post("/api/v1/auth/register", json=creds)
    r = client.post(
        "/api/v1/auth/login", json={"email": creds["email"], "password": creds["password"]}
    )
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> None:
    async def _delete() -> None:
        async with db_engine.AsyncSessionLocal() as session:
            await session.execute(text("DELETE FROM tenants WHERE slug IN ('soc-co', 'soc-two')"))
            await session.execute(
                text(
                    "DELETE FROM users WHERE email IN ('soc-admin@example.com', "
                    "'soc-other@example.com', 'soc-member@example.com')"
                )
            )
            await session.commit()

    asyncio.run(_delete())
    yield  # type: ignore[misc]
    asyncio.run(_delete())


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _register(_ADMIN)


@pytest.fixture(scope="module")
def other_token() -> str:
    return _register(_OTHER)


@pytest.fixture(scope="module")
def tenant_id(admin_token: str) -> UUID:
    return UUID(client.get("/api/v1/me", headers=_auth(admin_token)).json()["tenant_id"])


@pytest.fixture
def cid(admin_token: str) -> str:
    r = client.post("/api/v1/clients", json={"name": "Acme"}, headers=_auth(admin_token))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _account(token: str, client_id: str, platform: str = "facebook", handle: str = "@acme") -> Any:
    return client.post(
        f"/api/v1/clients/{client_id}/social-accounts",
        json={"platform": platform, "handle": handle},
        headers=_auth(token),
    )


def _import(token: str, account_id: str, content: str, **body: Any) -> Any:
    payload = {"kind": "posts", "format": "csv", "content": content, **body}
    return client.post(
        f"/api/v1/social-accounts/{account_id}/import", json=payload, headers=_auth(token)
    )


async def _member_token(tenant_id: UUID) -> str:
    async with db_engine.AsyncSessionLocal() as session:
        user = User(email="soc-member@example.com", hashed_password=hash_password("x-irrelevant-1"))
        session.add(user)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant_id, user_id=user.id)
        session.add(Membership(user_id=user.id, tenant_id=tenant_id, role="member"))
        await session.commit()
        return create_access_token(user.id, tenant_id, "member")


# ---------- the importer ----------


def test_each_platform_reads_its_own_export_columns() -> None:
    fb = parse_export("facebook", "posts", "csv", FB_CSV)
    assert fb.errors == [] and len(fb.rows) == 3
    first = fb.rows[0]
    assert first["ref"] == "p1" and first["format"] == "photo" and first["likes"] == 50
    assert first["clicks"] == 10 and first["posted_at"].tzinfo is not None

    li = parse_export(
        "linkedin", "posts", "csv",
        "Created date,Post title,Impressions,Unique impressions,Reactions,Reposts\n"
        "11/02/2026,Hello,100,80,9,3\n",
    )
    assert li.rows[0]["reach"] == 80 and li.rows[0]["shares"] == 3 and li.rows[0]["likes"] == 9
    assert li.rows[0]["ref"].startswith("2026-11-02")  # no id column: date + title


def test_json_and_daily_files_are_read() -> None:
    rows = [{"Date": "2026-11-01", "Followers": "1,000", "Reach": 5}]
    out = parse_export("instagram", "daily", "json", json.dumps({"rows": rows}))
    assert out.rows == [
        {"day": date(2026, 11, 1), "followers": 1000, "reach": 5, "impressions": 0}
    ]


def test_bad_rows_are_reported_and_good_ones_kept() -> None:
    out = parse_export(
        "facebook", "posts", "csv",
        "Publish time,Impressions\n2026-11-02,10\nnot a date,5\n2026-11-03,-4\n2026-11-04,abc\n",
    )
    assert len(out.rows) == 1
    assert [(e.row, e.message) for e in out.errors] == [
        (2, "Cannot read the date 'not a date'."),
        (3, "impressions cannot be negative."),
        (4, "impressions must be a number."),
    ]


@pytest.mark.parametrize(
    ("fmt", "content", "message"),
    [
        ("csv", "Impressions\n5\n", "Missing the 'publish_time' column"),
        ("csv", "", "no rows"),
        ("json", "{nope", "not valid JSON"),
        ("json", '"text"', "list of objects"),
        ("csv", "x" * 2_000_001, "too large"),
    ],
)
def test_an_unreadable_file_is_rejected(fmt: str, content: str, message: str) -> None:
    with pytest.raises(ImportFileError, match=message):
        parse_export("facebook", "posts", fmt, content)


def test_the_same_post_twice_in_a_file_keeps_the_last() -> None:
    out = parse_export(
        "facebook", "posts", "csv",
        "Post ID,Publish time,Reach\na,2026-11-02,1\na,2026-11-02,9\n",
    )
    assert [r["reach"] for r in out.rows] == [9]


# ---------- metrics ----------


def _post(day: int, hour: int, fmt: str, **n: int) -> dict[str, Any]:
    base = {"impressions": 0, "reach": 0, "likes": 0, "comments": 0, "shares": 0, "clicks": 0}
    return {
        **base, **n, "ref": f"{day}-{hour}", "title": None, "format": fmt,
        "posted_at": datetime(2026, 11, day, hour, tzinfo=timezone.utc),
    }


def test_metrics_are_computed_from_the_rows() -> None:
    posts = [
        _post(2, 9, "photo", impressions=1000, reach=800, likes=100),  # Monday
        _post(3, 18, "video", impressions=1000, reach=600, likes=300),  # Tuesday
        _post(16, 9, "photo", impressions=2000, reach=900, likes=50, clicks=50),  # 2 weeks on
    ]
    daily = [
        {"day": date(2026, 11, 1), "followers": 1000, "reach": 10, "impressions": 20},
        {"day": date(2026, 11, 20), "followers": 1100, "reach": 5, "impressions": 6},
    ]
    m = compute_metrics(posts, daily)
    assert m["followers"]["growth"] == 100 and m["followers"]["growth_pct"] == 10.0
    assert m["engagement_rate"] == 12.5  # 500 / 4000
    assert m["cadence"] == {"posts": 3, "per_week": 1.5}
    assert m["best_days"][0]["key"] == "Tue" and m["best_formats"][0]["key"] == "video"
    assert m["top_posts"][0]["engagements"] == 300
    assert m["trend"] == [
        {"week": "2026-10-26", "reach": 10, "impressions": 20},
        {"week": "2026-11-16", "reach": 5, "impressions": 6},
    ]
    without_daily = compute_metrics(posts, [])
    assert without_daily["followers"] is None
    assert without_daily["trend"][0] == {"week": "2026-11-02", "reach": 1400, "impressions": 2000}


def test_metrics_of_nothing_are_empty_not_errors() -> None:
    m = compute_metrics([], [])
    assert m["posts"] == 0 and m["engagement_rate"] is None and m["top_posts"] == []
    assert m["cadence"]["per_week"] is None


def test_bottom_posts_do_not_repeat_the_top_ones() -> None:
    posts = [_post(d, 9, "photo", likes=d) for d in range(1, 9)]
    m = compute_metrics(posts, [])
    top = {p["ref"] for p in m["top_posts"]}
    assert len(m["bottom_posts"]) == 3 and not top & {p["ref"] for p in m["bottom_posts"]}
    assert m["bottom_posts"][0]["engagements"] == 1


# ---------- the API ----------


def test_accounts_are_added_listed_and_deleted(admin_token: str, cid: str) -> None:
    r = _account(admin_token, cid, "instagram", "@acme_ig")
    assert r.status_code == 201 and r.json()["handle"] == "acme_ig"
    assert _account(admin_token, cid, "instagram", "acme_ig").status_code == 409
    assert _account(admin_token, cid, "tiktok").status_code == 422  # not a supported platform
    listed = client.get(f"/api/v1/clients/{cid}/social-accounts", headers=_auth(admin_token))
    assert [a["platform"] for a in listed.json()] == ["instagram"]
    done = client.delete(f"/api/v1/social-accounts/{r.json()['id']}", headers=_auth(admin_token))
    assert done.status_code == 204
    after = client.get(f"/api/v1/clients/{cid}/social-accounts", headers=_auth(admin_token))
    assert after.json() == []


def test_a_preview_saves_nothing_and_an_import_is_idempotent(admin_token: str, cid: str) -> None:
    account = _account(admin_token, cid).json()["id"]
    metrics_url = f"/api/v1/social-accounts/{account}/metrics"

    preview = _import(admin_token, account, FB_CSV).json()
    assert preview["committed"] is False and preview["valid"] == 3 and preview["errors"] == []
    assert preview["sample"][0]["ref"] == "p1"
    assert client.get(metrics_url, headers=_auth(admin_token)).json()["posts"] == 0

    saved = _import(admin_token, account, FB_CSV, commit=True).json()
    assert saved["committed"] is True
    _import(admin_token, account, FB_CSV, commit=True)  # again: updates, no duplicates
    m = client.get(metrics_url, headers=_auth(admin_token)).json()
    assert m["posts"] == 3 and m["platform"] == "facebook"
    assert m["top_posts"][0]["ref"] == "p2" and m["best_formats"][0]["key"] == "video"

    daily = _import(
        admin_token, account, "Date,Followers\n2026-11-01,100\n2026-11-30,150\n",
        kind="daily", commit=True,
    )
    assert daily.status_code == 200
    assert client.get(metrics_url, headers=_auth(admin_token)).json()["followers"]["growth"] == 50


def test_rows_with_errors_cannot_be_committed(admin_token: str, cid: str) -> None:
    account = _account(admin_token, cid).json()["id"]
    bad = "Publish time,Reach\n2026-11-02,1\nnope,2\n"
    assert _import(admin_token, account, bad).json()["errors"][0]["row"] == 2
    r = _import(admin_token, account, bad, commit=True)
    assert r.status_code == 422
    assert client.get(f"/api/v1/social-accounts/{account}/metrics",
                      headers=_auth(admin_token)).json()["posts"] == 0
    assert _import(admin_token, account, "Reach\n1\n").status_code == 422  # no date column


def test_members_read_but_cannot_change_and_tenants_are_isolated(
    admin_token: str, other_token: str, cid: str, tenant_id: UUID
) -> None:
    account = _account(admin_token, cid).json()["id"]
    member = asyncio.run(_member_token(tenant_id))
    assert _account(member, cid, "linkedin", "x").status_code == 403
    assert _import(member, account, FB_CSV).status_code == 403
    one = f"/api/v1/social-accounts/{account}"
    assert client.delete(one, headers=_auth(member)).status_code == 403
    assert client.get(f"{one}/metrics", headers=_auth(member)).status_code == 200
    assert client.get("/api/v1/social-templates", headers=_auth(member)).json()["posts"]["facebook"]

    for url in (f"/api/v1/social-accounts/{account}/metrics",
                f"/api/v1/clients/{cid}/social-accounts"):
        assert client.get(url, headers=_auth(other_token)).status_code == 404
    assert _import(other_token, account, FB_CSV).status_code == 404
    assert _account(other_token, cid).status_code == 404
