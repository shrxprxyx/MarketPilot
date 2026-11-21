"""AI gateway (SRS §3.7): resolve route -> decrypt key in memory -> provider
adapter -> retry / fallback / schema validation -> record usage.

Usage rows are staged on the session (like log_audit); the caller's commit
persists them.
"""
import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.budget import hard_stop_reached
from app.ai.providers import ADAPTERS, Completion, Message, ProviderError, TransientProviderError
from app.core.crypto import decrypt_secret
from app.models.ai_connection import AIConnection
from app.models.model_pricing import ModelPricing
from app.models.task_model_route import TaskModelRoute
from app.models.usage_log import UsageLog

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 3  # per target: initial try + 2 retries on transient errors
BACKOFF_SECONDS = 0.5


class GatewayError(Exception):
    """Safe-to-show failure (no route, provider down, invalid output)."""


class BudgetExceededError(GatewayError):
    """The tenant's monthly budget is reached and its hard stop is on."""


class NoRouteError(GatewayError):
    """The tenant has no usable route for the task (not set up, or its connection is gone)."""


@dataclass
class GatewayResult:
    text: str
    parsed: BaseModel | None
    model: str
    provider: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal | None


@dataclass
class _Target:
    connection: AIConnection
    model: str


async def _price(db: AsyncSession, provider: str, model: str) -> tuple[Decimal, Decimal] | None:
    if provider == "ollama":
        return Decimal(0), Decimal(0)  # local models are priced at zero
    row = await db.scalar(
        select(ModelPricing).where(ModelPricing.provider == provider, ModelPricing.model == model)
    )
    return (row.input_per_mtok, row.output_per_mtok) if row else None


def compute_cost(price: tuple[Decimal, Decimal] | None, tin: int, tout: int) -> Decimal | None:
    if price is None:
        return None
    return (Decimal(tin) * price[0] + Decimal(tout) * price[1]) / Decimal(1_000_000)


async def _targets(
    db: AsyncSession, tenant_id: UUID, task: str
) -> tuple[TaskModelRoute, list[_Target]]:
    route = await db.scalar(
        select(TaskModelRoute).where(
            TaskModelRoute.tenant_id == tenant_id, TaskModelRoute.task_type == task
        )
    )
    if route is None:
        raise NoRouteError(f"No model route is configured for task '{task}'.")

    async def _conn(conn_id: UUID) -> AIConnection | None:
        found: AIConnection | None = await db.scalar(
            select(AIConnection).where(
                AIConnection.id == conn_id,
                AIConnection.tenant_id == tenant_id,
                AIConnection.is_active.is_(True),
            )
        )
        return found

    targets: list[_Target] = []
    primary = await _conn(route.connection_id)
    if primary:
        targets.append(_Target(primary, route.model))
    if route.fallback_connection_id and route.fallback_model:
        fallback = await _conn(route.fallback_connection_id)
        if fallback:
            targets.append(_Target(fallback, route.fallback_model))
    if not targets:
        raise NoRouteError(f"The connection for task '{task}' is missing or inactive.")
    return route, targets


async def _call(
    target: _Target,
    route: TaskModelRoute,
    messages: list[Message],
    schema: type[BaseModel] | None,
) -> tuple[Completion, BaseModel | None, int]:
    """One target: retry transient errors, and re-ask once on invalid output."""
    conn = target.connection
    key = decrypt_secret(conn.api_key_enc) if conn.api_key_enc else None  # memory only
    json_schema: dict[str, Any] | None = schema.model_json_schema() if schema else None
    adapter = ADAPTERS[conn.provider]
    invalid_output_retries = 1
    attempt = 0
    while True:
        attempt += 1
        started = time.monotonic()
        try:
            completion = await adapter.complete(
                base_url=conn.base_url,
                api_key=key,
                model=target.model,
                messages=messages,
                temperature=route.temperature,
                max_tokens=route.max_tokens,
                json_schema=json_schema,
            )
        except TransientProviderError:
            if attempt >= MAX_ATTEMPTS:
                raise
            await asyncio.sleep(BACKOFF_SECONDS * attempt)
            continue
        latency_ms = int((time.monotonic() - started) * 1000)
        if schema is None:
            return completion, None, latency_ms
        try:
            return completion, schema.model_validate_json(completion.text), latency_ms
        except ValidationError as exc:
            if invalid_output_retries == 0:
                raise ProviderError(
                    "The model returned output that does not match the schema."
                ) from exc
            invalid_output_retries -= 1


async def complete(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    task: str,
    messages: list[Message],
    client_id: UUID | None = None,
    schema: type[T] | None = None,
) -> GatewayResult:
    if await hard_stop_reached(db, tenant_id):
        raise BudgetExceededError(
            "Monthly AI budget reached. An admin can raise it in AI models."
        )
    route, targets = await _targets(db, tenant_id, task)
    last_error: ProviderError | None = None
    for target in targets:
        try:
            completion, parsed, latency_ms = await _call(target, route, messages, schema)
        except ProviderError as exc:
            last_error = exc
            continue
        provider = target.connection.provider
        cost = compute_cost(
            await _price(db, provider, target.model), completion.tokens_in, completion.tokens_out
        )
        db.add(
            UsageLog(
                tenant_id=tenant_id,
                connection_id=target.connection.id,
                provider=provider,
                task_type=task,
                client_id=client_id,
                model=target.model,
                tokens_in=completion.tokens_in,
                tokens_out=completion.tokens_out,
                cost_usd=cost,
                latency_ms=latency_ms,
                created_by=user_id,
            )
        )
        await db.flush()
        return GatewayResult(
            text=completion.text,
            parsed=parsed,
            model=target.model,
            provider=provider,
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_usd=cost,
        )
    raise GatewayError(str(last_error) if last_error else "The model call failed.")
