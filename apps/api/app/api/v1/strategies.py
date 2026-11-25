"""Strategy endpoints (FR-STR-01/04/07, FR-RAG-05). Admins and managers generate
(§2.2); every role can read."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import BudgetExceededError, GatewayError, NoRouteError, UnpricedModelError
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.core import idempotency
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.pagination import decode_cursor, encode_cursor
from app.core.rate_limit import rate_limit
from app.core.request import client_ip
from app.db.session import get_db
from app.jobs.service import validate_idempotency_key
from app.models.client import Client
from app.models.strategy import Strategy
from app.strategy.generator import generate_strategy

router = APIRouter(tags=["strategies"])

DB = Annotated[AsyncSession, Depends(get_db)]
WRITER = require_role("admin", "manager")
IDEMPOTENCY_SCOPE = "strategy.generate"


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
    warnings: list[str]
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal | None
    created_at: datetime


class StrategyListOut(BaseModel):
    items: list[StrategyOut]
    next_cursor: str | None


async def _client_or_404(db: AsyncSession, current: CurrentUser, client_id: UUID) -> Client:
    client = await db.scalar(
        select(Client).where(Client.id == client_id, Client.tenant_id == current.tenant_id)
    )
    if not client:
        raise ProblemException(404, "Not Found", "Client not found.")
    return client


async def _strategy_or_404(db: AsyncSession, current: CurrentUser, strategy_id: UUID) -> Strategy:
    strategy = await db.scalar(
        select(Strategy).where(Strategy.id == strategy_id, Strategy.tenant_id == current.tenant_id)
    )
    if not strategy:
        raise ProblemException(404, "Not Found", "Strategy not found.")
    return strategy


@router.post(
    "/clients/{client_id}/strategies",
    response_model=StrategyOut,
    status_code=201,
    dependencies=[rate_limit("strategy.generate", user=10, tenant=30)],
)
async def create_strategy(
    client_id: UUID,
    body: GenerateIn,
    request: Request,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> StrategyOut:
    """Generate a new version. With an `Idempotency-Key` header, a retried request returns the
    strategy the first one made instead of calling (and billing) the model again."""
    key = validate_idempotency_key(request.headers.get("Idempotency-Key"))
    client = await _client_or_404(db, current, client_id)
    if key is None:
        return await _generate(db, request, current, client, body.month)

    fingerprint = f"{client_id}|{body.month}"
    done = await idempotency.claim(IDEMPOTENCY_SCOPE, current.tenant_id, key, fingerprint)
    if done is not None:
        return StrategyOut.model_validate(await _strategy_or_404(db, current, done))
    try:
        out = await _generate(db, request, current, client, body.month)
    except BaseException:  # includes cancellation: never leave the key reserved
        await idempotency.release(IDEMPOTENCY_SCOPE, current.tenant_id, key)
        raise
    await idempotency.complete(IDEMPOTENCY_SCOPE, current.tenant_id, key, fingerprint, out.id)
    return out


async def _generate(
    db: AsyncSession, request: Request, current: CurrentUser, client: Client, month: str
) -> StrategyOut:
    if client.status == "archived":
        raise ProblemException(409, "Conflict", "Restore this client before generating.")
    try:
        strategy = await generate_strategy(
            db,
            tenant_id=current.tenant_id,
            user_id=current.user.id,
            client=client,
            month=month,
        )
    except BudgetExceededError as exc:
        raise ProblemException(402, "Payment Required", str(exc)) from exc
    except UnpricedModelError as exc:
        raise ProblemException(409, "Conflict", str(exc)) from exc
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
        meta={"client_id": str(client.id), "month": month, "version": strategy.version},
        ip=client_ip(request),
    )
    await db.refresh(strategy)  # server defaults (created_at); RLS context is gone after commit
    out = StrategyOut.model_validate(strategy)
    await db.commit()
    return out


@router.get("/clients/{client_id}/strategies", response_model=StrategyListOut)
async def list_strategies(
    client_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> StrategyListOut:
    """Newest month first, then newest version. The cursor is the last strategy returned."""
    await _client_or_404(db, current, client_id)
    stmt = (
        select(Strategy)
        .where(Strategy.client_id == client_id, Strategy.tenant_id == current.tenant_id)
        .order_by(Strategy.month.desc(), Strategy.version.desc())
        .limit(limit + 1)
    )
    if cursor:
        try:
            _, last_id = decode_cursor(cursor)
        except ValueError as exc:
            raise ProblemException(400, "Bad Request", "Invalid cursor.") from exc
        last = (
            await db.execute(
                select(Strategy.month, Strategy.version).where(
                    Strategy.id == last_id,
                    Strategy.client_id == client_id,
                    Strategy.tenant_id == current.tenant_id,
                )
            )
        ).one_or_none()
        if last is None:
            raise ProblemException(400, "Bad Request", "Invalid cursor.")
        stmt = stmt.where(tuple_(Strategy.month, Strategy.version) < (last.month, last.version))
    rows = list(await db.scalars(stmt))
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    return StrategyListOut(
        items=[StrategyOut.model_validate(r) for r in page], next_cursor=next_cursor
    )


@router.get("/strategies/{strategy_id}", response_model=StrategyOut)
async def get_strategy(
    strategy_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], db: DB
) -> Strategy:
    return await _strategy_or_404(db, current, strategy_id)
