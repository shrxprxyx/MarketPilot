"""
DB-level tenant isolation for the Phase 2 tables (FR-TEN-05, SRS §11): ai_connections,
task_model_routes, documents, document_chunks, usage_logs, strategies, jobs, audits and
audit_findings. These use the plain
tenant_id-only policy; the API-level 404 tests elsewhere do not prove the database enforces it,
so these run as the non-owner app_user with FORCE RLS, like production.
"""
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

import app.db.base_imports  # noqa: F401  (registers every model so the relationships resolve)
import app.db.engine as db_engine
from app.db.base import Base
from app.db.rls import set_rls_context
from app.models.ai_connection import AIConnection
from app.models.audit import Audit, AuditFinding
from app.models.client import Client
from app.models.document import EMBEDDING_DIM, Document, DocumentChunk
from app.models.job import Job
from app.models.strategy import Strategy
from app.models.task_model_route import TaskModelRoute
from app.models.tenant import Tenant
from app.models.usage_log import UsageLog

_SLUGS = ("iso-p2-alice-co", "iso-p2-bob-co")


@dataclass
class Parents:
    tenant_id: UUID
    client_id: UUID
    connection_id: UUID
    document_id: UUID
    audit_id: UUID


def _row(tenant_id: UUID, p: Parents, *, rogue: bool = False) -> dict[str, Callable[[], Base]]:
    """One row per table. `rogue` varies unique keys so a failed insert can only be RLS."""
    return {
        "ai_connections": lambda: AIConnection(
            tenant_id=tenant_id, provider="openai", label="k", api_key_enc="enc", key_last4="1234"
        ),
        "task_model_routes": lambda: TaskModelRoute(
            tenant_id=tenant_id,
            task_type="content" if rogue else "strategy",
            connection_id=p.connection_id,
            model="m",
        ),
        "documents": lambda: Document(
            tenant_id=tenant_id,
            client_id=p.client_id,
            source_type="brand_doc",
            title="Doc",
            content="text",
            content_hash=uuid.uuid4().hex,
            status="ready",
        ),
        "document_chunks": lambda: DocumentChunk(
            tenant_id=tenant_id,
            document_id=p.document_id,
            client_id=p.client_id,
            chunk_index=1 if rogue else 0,
            text="chunk",
            embedding=[0.0] * EMBEDDING_DIM,
        ),
        "usage_logs": lambda: UsageLog(
            tenant_id=tenant_id,
            provider="openai",
            task_type="strategy",
            model="gpt-4o-mini",
            tokens_in=1,
            tokens_out=1,
            cost_usd=Decimal("0.000001"),
            latency_ms=1,
        ),
        "strategies": lambda: Strategy(
            tenant_id=tenant_id,
            client_id=p.client_id,
            month="2026-12",
            version=2 if rogue else 1,
            plan={},
            provider="openai",
            model_used="gpt-4o-mini",
            sources=[],
            tokens_in=1,
            tokens_out=1,
        ),
        "jobs": lambda: Job(tenant_id=tenant_id, type="document.index", payload={}),
        "audits": lambda: Audit(
            tenant_id=tenant_id, client_id=p.client_id, type="website", url="https://a.test"
        ),
        "audit_findings": lambda: AuditFinding(
            tenant_id=tenant_id, audit_id=p.audit_id, code="c", category="links",
            severity="low", title="t", detail="d", recommendation="r", metric={},
        ),
    }


TABLES = list(_row(uuid.uuid4(), Parents(*(uuid.uuid4(),) * 5)))


async def _cleanup() -> None:
    async with db_engine.AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM tenants WHERE slug = ANY(:s)"), {"s": list(_SLUGS)})
        await session.commit()


async def _seed(name: str, slug: str) -> tuple[Parents, dict[str, UUID]]:
    async with db_engine.AsyncSessionLocal() as session:
        tenant = Tenant(name=name, slug=slug)
        session.add(tenant)
        await session.flush()
        await set_rls_context(session, tenant_id=tenant.id)
        client = Client(tenant_id=tenant.id, name="C")
        conn = AIConnection(
            tenant_id=tenant.id, provider="openai", label="parent", api_key_enc="e", key_last4="1"
        )
        session.add_all([client, conn])
        await session.flush()
        doc = Document(
            tenant_id=tenant.id,
            client_id=client.id,
            source_type="brand_doc",
            title="Parent",
            content="parent",
            content_hash=uuid.uuid4().hex,
            status="ready",
        )
        session.add(doc)
        await session.flush()
        audit = Audit(tenant_id=tenant.id, client_id=client.id, type="website", url="https://p.test")
        session.add(audit)
        await session.flush()
        parents = Parents(tenant.id, client.id, conn.id, doc.id, audit.id)
        ids: dict[str, UUID] = {}
        for table, make in _row(tenant.id, parents).items():
            obj: Any = make()
            session.add(obj)
            await session.flush()
            ids[table] = obj.id
        await session.commit()
        return parents, ids


@dataclass
class World:
    alice: Parents
    bob: Parents
    alice_ids: dict[str, UUID]
    bob_ids: dict[str, UUID]


@pytest.fixture
async def world() -> AsyncGenerator[World, None]:
    await _cleanup()
    alice, alice_ids = await _seed("Iso P2 Alice Co", _SLUGS[0])
    bob, bob_ids = await _seed("Iso P2 Bob Co", _SLUGS[1])
    yield World(alice, bob, alice_ids, bob_ids)
    await _cleanup()


async def _count(tenant_id: UUID | None, table: str, row_id: UUID) -> int:
    async with db_engine.AsyncSessionLocal() as session:
        if tenant_id is not None:
            await set_rls_context(session, tenant_id=tenant_id)
        result = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_id}
        )
        return int(result.scalar_one())


@pytest.mark.parametrize("table", TABLES)
async def test_tenant_sees_own_row_but_not_the_others(world: World, table: str) -> None:
    assert await _count(world.alice.tenant_id, table, world.alice_ids[table]) == 1
    assert await _count(world.alice.tenant_id, table, world.bob_ids[table]) == 0
    assert await _count(world.bob.tenant_id, table, world.alice_ids[table]) == 0


@pytest.mark.parametrize("table", TABLES)
async def test_no_tenant_context_sees_nothing(world: World, table: str) -> None:
    assert await _count(None, table, world.alice_ids[table]) == 0
    assert await _count(None, table, world.bob_ids[table]) == 0


@pytest.mark.parametrize("table", TABLES)
async def test_cross_tenant_insert_is_rejected(world: World, table: str) -> None:
    # Alice's context, Bob's tenant_id and Bob's own parent rows: only RLS can refuse it.
    rogue: Any = _row(world.bob.tenant_id, world.bob, rogue=True)[table]()
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=world.alice.tenant_id)
        session.add(rogue)
        with pytest.raises(Exception, match="row-level security"):
            await session.flush()
        await session.rollback()


@pytest.mark.parametrize("table", TABLES)
async def test_cross_tenant_update_and_delete_touch_nothing(world: World, table: str) -> None:
    target = world.bob_ids[table]
    async with db_engine.AsyncSessionLocal() as session:
        await set_rls_context(session, tenant_id=world.alice.tenant_id)
        updated = await session.execute(
            text(f"UPDATE {table} SET updated_at = now() WHERE id = :id"), {"id": target}
        )
        deleted = await session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": target})
        assert updated.rowcount == 0  # type: ignore[attr-defined]
        assert deleted.rowcount == 0  # type: ignore[attr-defined]
        await session.commit()
    assert await _count(world.bob.tenant_id, table, target) == 1  # Bob's row survived
