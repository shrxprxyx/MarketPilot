"""Budget and pre-flight estimate (FR-BYOM-05). Admins set the budget; admins and
managers read it and the estimate (§2.2)."""
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import BudgetStatus, get_budget_status
from app.ai.gateway import NoRouteError, _price, _targets, compute_cost
from app.auth.dependencies import CurrentUser, require_role
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.request import client_ip
from app.db.session import get_db
from app.models.client import Client
from app.models.tenant import Tenant
from app.rag.chunking import CHARS_PER_TOKEN
from app.strategy.generator import prepare_prompt

router = APIRouter(tags=["ai"])

DB = Annotated[AsyncSession, Depends(get_db)]
ADMIN = require_role("admin")
VIEWER = require_role("admin", "manager")
_SIX_PLACES = Decimal("0.000001")


class BudgetIn(BaseModel):
    monthly_budget_usd: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    hard_stop: bool = False


class BudgetOut(BaseModel):
    monthly_budget_usd: Decimal | None
    hard_stop: bool
    spent_usd: Decimal
    percent_used: float | None
    unpriced_calls: int
    month: str


class EstimateOut(BaseModel):
    tokens_in_est: int
    tokens_out_max: int
    cost_max_usd: Decimal | None  # null = no price known for the model
    model: str


def _out(s: BudgetStatus) -> BudgetOut:
    percent = (
        round(float(s.spent_usd / s.monthly_budget_usd * 100), 1)
        if s.monthly_budget_usd
        else None
    )
    return BudgetOut(
        monthly_budget_usd=s.monthly_budget_usd,
        hard_stop=s.hard_stop,
        spent_usd=s.spent_usd,
        percent_used=percent,
        unpriced_calls=s.unpriced_calls,
        month=s.month,
    )


@router.get("/ai/budget", response_model=BudgetOut)
async def get_budget(current: Annotated[CurrentUser, VIEWER], db: DB) -> BudgetOut:
    return _out(await get_budget_status(db, current.tenant_id))


@router.put("/ai/budget", response_model=BudgetOut)
async def put_budget(
    body: BudgetIn, request: Request, current: Annotated[CurrentUser, ADMIN], db: DB
) -> BudgetOut:
    tenant = await db.get(Tenant, current.tenant_id)
    if tenant is None:  # cannot happen for an authenticated member; keeps mypy honest
        raise ProblemException(404, "Not Found", "Tenant not found.")
    tenant.monthly_budget_usd = body.monthly_budget_usd
    tenant.hard_stop = body.hard_stop
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="ai_budget.updated",
        entity="tenant",
        entity_id=current.tenant_id,
        meta={
            "monthly_budget_usd": None
            if body.monthly_budget_usd is None
            else str(body.monthly_budget_usd),
            "hard_stop": body.hard_stop,
        },
        ip=client_ip(request),
    )
    await db.flush()
    out = _out(await get_budget_status(db, current.tenant_id))
    await db.commit()
    return out


@router.get("/ai/usage/estimate", response_model=EstimateOut)
async def estimate(
    current: Annotated[CurrentUser, VIEWER],
    db: DB,
    client_id: UUID,
    month: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    task: Literal["strategy"] = "strategy",
) -> EstimateOut:
    """Pre-flight estimate: builds the real prompt but never calls the model. Input tokens
    are characters / CHARS_PER_TOKEN; the cost is a maximum (output at the route's cap)."""
    client = await db.scalar(
        select(Client).where(Client.id == client_id, Client.tenant_id == current.tenant_id)
    )
    if not client:
        raise ProblemException(404, "Not Found", "Client not found.")
    try:
        route, targets = await _targets(db, current.tenant_id, task)
    except NoRouteError as exc:
        raise ProblemException(
            409, "Conflict", "Set up a model for the strategy task in AI models."
        ) from exc
    messages, _ = await prepare_prompt(db, tenant_id=current.tenant_id, client=client, month=month)
    tokens_in = sum(len(m["content"]) for m in messages) // CHARS_PER_TOKEN
    target = targets[0]
    cost = compute_cost(
        await _price(db, target.connection.provider, target.model), tokens_in, route.max_tokens
    )
    return EstimateOut(
        tokens_in_est=tokens_in,
        tokens_out_max=route.max_tokens,
        cost_max_usd=None if cost is None else cost.quantize(_SIX_PLACES),
        model=target.model,
    )
