from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import ADAPTERS, ProviderError
from app.auth.dependencies import CurrentUser, require_role
from app.core.audit import log_audit
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.errors import ProblemException
from app.core.request import client_ip
from app.db.session import get_db
from app.models.ai_connection import AIConnection
from app.models.task_model_route import TaskModelRoute

router = APIRouter(prefix="/ai/connections", tags=["ai"])

DB = Annotated[AsyncSession, Depends(get_db)]
# §2.2: admins and managers manage AI connections.
WRITER = require_role("admin", "manager")

Provider = Literal["openai", "anthropic", "ollama", "openai_compatible"]


class ConnectionIn(BaseModel):
    provider: Provider
    label: str = Field(min_length=1, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, min_length=4, max_length=500)

    @model_validator(mode="after")
    def _check_provider_fields(self) -> "ConnectionIn":
        if self.provider in ("ollama", "openai_compatible") and not self.base_url:
            raise ValueError("base_url is required for this provider")
        if self.provider != "ollama" and not self.api_key:
            raise ValueError("api_key is required for this provider")
        if self.base_url and not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return self


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    label: str
    base_url: str | None
    key_last4: str | None
    is_active: bool


class TestOut(BaseModel):
    ok: bool
    models: list[str]


async def _get_or_404(db: AsyncSession, current: CurrentUser, conn_id: UUID) -> AIConnection:
    conn = await db.scalar(
        select(AIConnection).where(
            AIConnection.id == conn_id, AIConnection.tenant_id == current.tenant_id
        )
    )
    if not conn:
        raise ProblemException(404, "Not Found", "AI connection not found.")
    return conn


@router.post("", response_model=ConnectionOut, status_code=201)
async def create_connection(
    body: ConnectionIn, request: Request, current: Annotated[CurrentUser, WRITER], db: DB
) -> AIConnection:
    conn = AIConnection(
        tenant_id=current.tenant_id,
        provider=body.provider,
        label=body.label,
        base_url=body.base_url,
        api_key_enc=encrypt_secret(body.api_key) if body.api_key else None,
        key_last4=body.api_key[-4:] if body.api_key else None,
    )
    db.add(conn)
    await db.flush()
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="ai_connection.created",
        entity="ai_connection",
        entity_id=conn.id,
        meta={"provider": body.provider, "label": body.label},
        ip=client_ip(request),
    )
    await db.commit()
    return conn


@router.get("", response_model=list[ConnectionOut])
async def list_connections(current: Annotated[CurrentUser, WRITER], db: DB) -> list[AIConnection]:
    rows = await db.scalars(
        select(AIConnection)
        .where(AIConnection.tenant_id == current.tenant_id)
        .order_by(AIConnection.created_at.desc())
    )
    return list(rows)


@router.post("/{conn_id}/test", response_model=TestOut)
async def test_connection(
    conn_id: UUID, current: Annotated[CurrentUser, WRITER], db: DB
) -> TestOut:
    conn = await _get_or_404(db, current, conn_id)
    key = decrypt_secret(conn.api_key_enc) if conn.api_key_enc else None
    try:
        models = await ADAPTERS[conn.provider].list_models(conn.base_url, key)
    except ProviderError as exc:
        raise ProblemException(400, "Connection Test Failed", str(exc)) from exc
    return TestOut(ok=True, models=models)


@router.delete("/{conn_id}", status_code=204)
async def delete_connection(
    conn_id: UUID, request: Request, current: Annotated[CurrentUser, WRITER], db: DB
) -> None:
    conn = await _get_or_404(db, current, conn_id)
    # Routes reference connections with ON DELETE CASCADE, so deleting one in use would
    # silently remove its routing and break the next generation. Make that a deliberate step.
    used_by = sorted(
        await db.scalars(
            select(TaskModelRoute.task_type).where(
                TaskModelRoute.tenant_id == current.tenant_id,
                or_(
                    TaskModelRoute.connection_id == conn.id,
                    TaskModelRoute.fallback_connection_id == conn.id,
                ),
            )
        )
    )
    if used_by:
        raise ProblemException(
            409,
            "Conflict",
            f"This connection is used for routing ({', '.join(used_by)}). "
            "Change the routing first, then delete it.",
        )
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="ai_connection.deleted",
        entity="ai_connection",
        entity_id=conn.id,
        meta={"provider": conn.provider, "label": conn.label},
        ip=client_ip(request),
    )
    await db.delete(conn)
    await db.commit()
