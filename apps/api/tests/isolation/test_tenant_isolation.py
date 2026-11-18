"""
DB-level tenant isolation (FR-TEN-05).

These tests talk to Postgres directly through the app's own session factory
(connected as app_user, the non-owner role the API runs as) and never go through
HTTP, so they prove the RLS policies themselves — not just that the routers happen
to filter correctly. Two tenants are created, and every combination of RLS context
is checked against `memberships`, the one tenant-scoped table that exists so far.
"""
from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
from sqlalchemy import select, text

import app.db.engine as db_engine
from app.auth.password import hash_password
from app.db.rls import set_rls_context
from app.models.membership import Membership
from app.models.tenant import Tenant
from app.models.user import User

_ALICE_EMAIL = "iso-alice@example.com"
_BOB_EMAIL = "iso-bob@example.com"
_ALICE_SLUG = "iso-alice-co"
_BOB_SLUG = "iso-bob-co"


async def _cleanup() -> None:
    async with db_engine.AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM tenants WHERE slug IN (:a, :b)"),
            {"a": _ALICE_SLUG, "b": _BOB_SLUG},
        )
        await session.execute(
            text("DELETE FROM users WHERE email IN (:a, :b)"),
            {"a": _ALICE_EMAIL, "b": _BOB_EMAIL},
        )
        await session.commit()


async def _create_tenant_and_admin(
    email: str, tenant_name: str, slug: str
) -> tuple[UUID, UUID, UUID]:
    """Returns (user_id, tenant_id, membership_id)."""
    async with db_engine.AsyncSessionLocal() as session:
        user = User(email=email, hashed_password=hash_password("irrelevant-1234"))
        session.add(user)
        tenant = Tenant(name=tenant_name, slug=slug)
        session.add(tenant)
        await session.flush()

        await set_rls_context(session, tenant_id=tenant.id, user_id=user.id)
        membership = Membership(user_id=user.id, tenant_id=tenant.id, role="admin")
        session.add(membership)
        await session.flush()

        ids = (user.id, tenant.id, membership.id)
        await session.commit()
        return ids


@pytest.fixture
async def two_tenants() -> AsyncGenerator[dict[str, UUID], None]:
    await _cleanup()
    alice_user, alice_tenant, alice_membership = await _create_tenant_and_admin(
        _ALICE_EMAIL, "Iso Alice Co", _ALICE_SLUG
    )
    bob_user, bob_tenant, bob_membership = await _create_tenant_and_admin(
        _BOB_EMAIL, "Iso Bob Co", _BOB_SLUG
    )
    yield {
        "alice_user": alice_user,
        "alice_tenant": alice_tenant,
        "alice_membership": alice_membership,
        "bob_user": bob_user,
        "bob_tenant": bob_tenant,
        "bob_membership": bob_membership,
    }
    await _cleanup()


async def test_tenant_context_cannot_see_other_tenants_membership(
    two_tenants: dict[str, UUID],
) -> None:
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=two_tenants["alice_tenant"])
        rows = (
            await session.execute(
                select(Membership).where(Membership.id == two_tenants["bob_membership"])
            )
        ).scalars().all()
        assert rows == [], "Alice's tenant context must not see Bob's membership row"


async def test_tenant_context_can_see_own_membership(two_tenants: dict[str, UUID]) -> None:
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=two_tenants["alice_tenant"])
        rows = (
            await session.execute(
                select(Membership).where(Membership.id == two_tenants["alice_membership"])
            )
        ).scalars().all()
        assert len(rows) == 1


async def test_no_rls_context_sees_nothing(two_tenants: dict[str, UUID]) -> None:
    """With neither app.tenant_id nor app.user_id set, FORCE RLS default-denies."""
    async with db_engine.AsyncSessionLocal() as session:
        rows = (await session.execute(select(Membership))).scalars().all()
        assert rows == []


async def test_user_context_sees_only_own_membership_across_tenants(
    two_tenants: dict[str, UUID],
) -> None:
    """Login needs to resolve a user's own membership before a tenant is chosen;
    the user_id branch must not leak into seeing *other* users' rows."""
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, user_id=two_tenants["alice_user"])
        rows = (await session.execute(select(Membership))).scalars().all()
        assert [r.id for r in rows] == [two_tenants["alice_membership"]]


async def test_cross_tenant_insert_is_rejected(two_tenants: dict[str, UUID]) -> None:
    """Writes do NOT get the user_id escape hatch: scoped to Alice's tenant, you
    cannot insert a membership row under Bob's tenant_id even for your own user."""
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(
            session, tenant_id=two_tenants["alice_tenant"], user_id=two_tenants["alice_user"]
        )
        rogue = Membership(
            user_id=two_tenants["alice_user"],
            tenant_id=two_tenants["bob_tenant"],
            role="admin",
        )
        session.add(rogue)
        with pytest.raises(Exception):  # noqa: B017 — asserting the DB rejects it
            await session.flush()
        await session.rollback()
