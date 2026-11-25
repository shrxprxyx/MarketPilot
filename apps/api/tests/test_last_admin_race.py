"""FR-TEN-01: an agency can never be left without an active admin, even when two admins
demote or deactivate each other at the same moment."""
import threading
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.auth.jwt import create_access_token
from app.auth.password import hash_password
from app.config import settings
from app.main import app

_SLUG = "lastadmin-race-co"
_EMAILS = ("lastadmin-one@example.com", "lastadmin-two@example.com")
ROUNDS = 15


@pytest.fixture
def two_admins() -> tuple[UUID, list[tuple[UUID, UUID]]]:
    """An agency with two active admins: returns (tenant_id, [(user_id, membership_id)...])."""
    engine = create_engine(settings.database_url_direct)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE slug = :s"), {"s": _SLUG})
        conn.execute(text("DELETE FROM users WHERE email = ANY(:e)"), {"e": list(_EMAILS)})
        tenant = conn.execute(
            text("INSERT INTO tenants (id, name, slug) VALUES (gen_random_uuid(), :n, :s) "
                 "RETURNING id"),
            {"n": "LastAdmin Race Co", "s": _SLUG},
        ).scalar_one()
        admins = []
        for email in _EMAILS:
            user = conn.execute(
                text("INSERT INTO users (id, email, hashed_password) "
                     "VALUES (gen_random_uuid(), :e, :h) RETURNING id"),
                {"e": email, "h": hash_password("irrelevant-1234")},
            ).scalar_one()
            membership = conn.execute(
                text("INSERT INTO memberships (id, user_id, tenant_id, role, status) "
                     "VALUES (gen_random_uuid(), :u, :t, 'admin', 'active') RETURNING id"),
                {"u": user, "t": tenant},
            ).scalar_one()
            admins.append((user, membership))
    yield tenant, admins
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE slug = :s"), {"s": _SLUG})
        conn.execute(text("DELETE FROM users WHERE email = ANY(:e)"), {"e": list(_EMAILS)})
    engine.dispose()


@pytest.mark.parametrize(
    ("change", "reset_status"),
    [({"role": "member"}, False), ({"status": "deactivated"}, True)],
    ids=["demote", "deactivate"],
)
def test_two_admins_cannot_remove_each_other_at_once(
    two_admins: tuple[UUID, list[tuple[UUID, UUID]]], change: dict[str, str], reset_status: bool
) -> None:
    tenant, admins = two_admins
    engine = create_engine(settings.database_url_direct)
    tokens = [create_access_token(user, tenant, "admin") for user, _ in admins]
    clients = [TestClient(app, raise_server_exceptions=False) for _ in admins]
    barrier = threading.Barrier(2)  # reusable: lines both requests up each round
    for _round in range(ROUNDS):
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE memberships SET role='admin', status='active' "
                     "WHERE tenant_id = :t"),
                {"t": tenant},
            )
        def attack(me: int, other: int) -> None:
            barrier.wait()
            clients[me].patch(
                f"/api/v1/members/{admins[other][1]}",
                json=change,
                headers={"Authorization": f"Bearer {tokens[me]}"},
            )

        threads = [
            threading.Thread(target=attack, args=(0, 1)),
            threading.Thread(target=attack, args=(1, 0)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with engine.begin() as conn:
            left = conn.execute(
                text("SELECT count(*) FROM memberships WHERE tenant_id = :t "
                     "AND role='admin' AND status='active'"),
                {"t": tenant},
            ).scalar_one()
        assert left >= 1, "the agency was left without an active admin"
    engine.dispose()
