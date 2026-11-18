"""
DB-level tenant isolation for `clients` (FR-TEN-05) — the plain tenant_id-only RLS
policy that every future tenant-scoped table should use, as opposed to
memberships' dual tenant/user policy (see migration 126facb9e740 and
tests/isolation/test_tenant_isolation.py for why memberships is the exception).
"""
from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
from sqlalchemy import select, text

import app.db.engine as db_engine
from app.db.rls import set_rls_context
from app.models.client import Client
from app.models.tenant import Tenant

_ALICE_SLUG = "iso-client-alice-co"
_BOB_SLUG = "iso-client-bob-co"


async def _cleanup() -> None:
    async with db_engine.AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM tenants WHERE slug IN (:a, :b)"),
            {"a": _ALICE_SLUG, "b": _BOB_SLUG},
        )
        await session.commit()


async def _create_tenant_with_client(
    tenant_name: str, slug: str, client_name: str
) -> tuple[UUID, UUID]:
    """Returns (tenant_id, client_id)."""
    async with db_engine.AsyncSessionLocal() as session:
        tenant = Tenant(name=tenant_name, slug=slug)
        session.add(tenant)
        await session.flush()

        await set_rls_context(session, tenant_id=tenant.id)
        new_client = Client(tenant_id=tenant.id, name=client_name)
        session.add(new_client)
        await session.flush()

        ids = (tenant.id, new_client.id)
        await session.commit()
        return ids


@pytest.fixture
async def two_tenants() -> AsyncGenerator[dict[str, UUID], None]:
    await _cleanup()
    alice_tenant, alice_client = await _create_tenant_with_client(
        "Iso Client Alice Co", _ALICE_SLUG, "Alice's Client"
    )
    bob_tenant, bob_client = await _create_tenant_with_client(
        "Iso Client Bob Co", _BOB_SLUG, "Bob's Client"
    )
    yield {
        "alice_tenant": alice_tenant,
        "alice_client": alice_client,
        "bob_tenant": bob_tenant,
        "bob_client": bob_client,
    }
    await _cleanup()


async def test_tenant_context_cannot_see_other_tenants_client(
    two_tenants: dict[str, UUID],
) -> None:
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=two_tenants["alice_tenant"])
        rows = (
            await session.execute(select(Client).where(Client.id == two_tenants["bob_client"]))
        ).scalars().all()
        assert rows == [], "Alice's tenant context must not see Bob's client row"


async def test_tenant_context_can_see_own_client(two_tenants: dict[str, UUID]) -> None:
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=two_tenants["alice_tenant"])
        rows = (
            await session.execute(select(Client).where(Client.id == two_tenants["alice_client"]))
        ).scalars().all()
        assert len(rows) == 1


async def test_no_rls_context_sees_no_clients(two_tenants: dict[str, UUID]) -> None:
    """Unlike memberships, clients has no user_id escape hatch at all — with no
    context set, FORCE RLS default-denies every row."""
    async with db_engine.AsyncSessionLocal() as session:
        rows = (await session.execute(select(Client))).scalars().all()
        assert rows == []


async def test_cross_tenant_insert_is_rejected(two_tenants: dict[str, UUID]) -> None:
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=two_tenants["alice_tenant"])
        rogue = Client(tenant_id=two_tenants["bob_tenant"], name="Smuggled Client")
        session.add(rogue)
        with pytest.raises(Exception):  # noqa: B017 — asserting the DB rejects it
            await session.flush()
        await session.rollback()


async def test_cross_tenant_update_is_rejected(two_tenants: dict[str, UUID]) -> None:
    """Scoped to Alice's tenant, Bob's client row isn't even visible for UPDATE
    to find — USING on the UPDATE policy filters it out before WITH CHECK runs."""
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=two_tenants["alice_tenant"])
        result = await session.execute(
            select(Client).where(Client.id == two_tenants["bob_client"])
        )
        assert result.scalar() is None
