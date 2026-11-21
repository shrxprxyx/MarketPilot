"""Strategy endpoints (FR-STR-01/04/07, FR-RAG-05). Admins and managers generate
(§2.2); every role can read."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import BudgetExceededError, GatewayError, NoRouteError
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.request import client_ip
from app.db.session import get_db
from app.models.client import Client
from app.models.strategy import Strategy
from app.strategy.generator import generate_strategy

router = APIRouter(tags=["strategies"])

DB = Annotated[AsyncSession, Depends(get_db)]
WRITER = require_role("admin", "manager")
LIST_LIMIT = 50


class GenerateIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class StrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    month: str
    version: int
    status: str
    plan: dict[str, Any]
    provider: str
    model_used: str
    sources: list[dict[str, Any]]
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal | None
    created_at: datetime


async def _client_or_404(db: AsyncSession, current: CurrentUser, client_id: UUID) -> Client:
    client = await db.scalar(
        select(Client).where(Client.id == client_id, Client.tenant_id == current.tenant_id)
    )
    if not client:
        raise ProblemException(404, "Not Found", "Client not found.")
    return client


@router.post("/clients/{client_id}/strategies", response_model=StrategyOut, status_code=201)
async def create_strategy(
    client_id: UUID,
    body: GenerateIn,
    request: Request,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> StrategyOut:
    client = await _client_or_404(db, current, client_id)
    if client.status == "archived":
        raise ProblemException(409, "Conflict", "Restore this client before generating.")
    try:
        strategy = await generate_strategy(
            db,
            tenant_id=current.tenant_id,
            user_id=current.user.id,
            client=client,
            month=body.month,
        )
    except BudgetExceededError as exc:
        raise ProblemException(402, "Payment Required", str(exc)) from exc
    except NoRouteError as exc:
        raise ProblemException(
            409, "Conflict", "Set up a model for the strategy task in AI models."
        ) from exc
    except GatewayError as exc:
        raise ProblemException(502, "Bad Gateway", str(exc)) from exc
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="strategy.generate",
        entity="strategy",
        entity_id=strategy.id,
        meta={"client_id": str(client_id), "month": body.month, "version": strategy.version},
        ip=client_ip(request),
    )
    await db.refresh(strategy)  # server defaults (created_at); RLS context is gone after commit
    out = StrategyOut.model_validate(strategy)
    await db.commit()
    return out


@router.get("/clients/{client_id}/strategies", response_model=list[StrategyOut])
async def list_strategies(
    client_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], db: DB
) -> list[Strategy]:
    await _client_or_404(db, current, client_id)
    rows = await db.scalars(
        select(Strategy)
        .where(Strategy.client_id == client_id, Strategy.tenant_id == current.tenant_id)
        .order_by(Strategy.month.desc(), Strategy.version.desc())
        .limit(LIST_LIMIT)
    )
    return list(rows)


@router.get("/strategies/{strategy_id}", response_model=StrategyOut)
async def get_strategy(
    strategy_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], db: DB
) -> Strategy:
    strategy = await db.scalar(
        select(Strategy).where(Strategy.id == strategy_id, Strategy.tenant_id == current.tenant_id)
    )
    if not strategy:
        raise ProblemException(404, "Not Found", "Strategy not found.")
    return strategy
