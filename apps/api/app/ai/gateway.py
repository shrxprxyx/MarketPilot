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

from app.ai.budget import hard_stop_active, hard_stop_reached
from app.ai.providers import ADAPTERS, Completion, Message, ProviderError, TransientProviderError
from app.core.crypto import decrypt_secret
from app.models.ai_connection import AIConnection
from app.models.model_pricing import ModelPricing
from app.models.task_model_route import TaskModelRoute
from app.models.usage_log import UsageLog

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 3  # per target: initial try + 2 retries on transient errors
MAX_REPAIR_RETRIES = 2  # per target: re-asks when the reply does not match the schema
BACKOFF_SECONDS = 0.5
# Upper bound for one whole gateway call (every retry and fallback). The request holds a
# database connection while it waits, so without this a slow provider could pin it for
# MAX_ATTEMPTS x 2 targets x the per-request timeout.
GATEWAY_DEADLINE_SECONDS = 300.0


class GatewayError(Exception):
    """Safe-to-show failure (no route, provider down, invalid output)."""


class BudgetExceededError(GatewayError):
    """The tenant's monthly budget is reached and its hard stop is on."""


class UnpricedModelError(GatewayError):
    """A hard-stopped budget cannot be enforced for a model whose price is unknown."""


class NoRouteError(GatewayError):
    """The tenant has no usable route for the task (not set up, or its connection is gone)."""


class WastedUsageError(ProviderError):
    """A call failed after earlier attempts had already consumed tokens (output that did not
    match the schema, then a provider failure or more invalid output). The tokens are carried
    along so they can still be recorded as usage."""

    def __init__(self, message: str, tokens_in: int, tokens_out: int, latency_ms: int) -> None:
        super().__init__(message)
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.latency_ms = latency_ms


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


def _repair_prompt(exc: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}" for e in exc.errors()[:5]
    )
    return (
        f"Your previous reply did not match the required JSON schema ({problems}). "
        "Reply again with only a valid JSON object that matches the schema."
    )


def _raise_keeping_spent_tokens(
    exc: ProviderError, tokens_in: int, tokens_out: int, started: float
) -> None:
    """If earlier attempts of this call already consumed tokens, fail in a way that carries
    them, so the spend is still recorded."""
    if tokens_in or tokens_out:
        latency_ms = int((time.monotonic() - started) * 1000)
        raise WastedUsageError(str(exc), tokens_in, tokens_out, latency_ms) from exc


async def _call(
    target: _Target,
    route: TaskModelRoute,
    messages: list[Message],
    schema: type[BaseModel] | None,
) -> tuple[Completion, BaseModel | None, int]:
    """One target: retry transient errors, and re-ask (telling the model what was wrong) when
    the output does not match the schema. Tokens of every attempt are summed in the result."""
    conn = target.connection
    key = decrypt_secret(conn.api_key_enc) if conn.api_key_enc else None  # memory only
    json_schema: dict[str, Any] | None = schema.model_json_schema() if schema else None
    adapter = ADAPTERS[conn.provider]
    repair_retries = MAX_REPAIR_RETRIES
    conversation = messages
    tokens_in = tokens_out = 0
    attempt = 0  # transient failures of the current request; a repair re-ask starts afresh
    started = time.monotonic()
    while True:
        attempt += 1
        try:
            completion = await adapter.complete(
                base_url=conn.base_url,
                api_key=key,
                model=target.model,
                messages=conversation,
                temperature=route.temperature,
                max_tokens=route.max_tokens,
                json_schema=json_schema,
            )
        except TransientProviderError as exc:
            if attempt >= MAX_ATTEMPTS:
                _raise_keeping_spent_tokens(exc, tokens_in, tokens_out, started)
                raise
            await asyncio.sleep(BACKOFF_SECONDS * attempt)
            continue
        except ProviderError as exc:
            _raise_keeping_spent_tokens(exc, tokens_in, tokens_out, started)
            raise
        attempt = 0
        tokens_in += completion.tokens_in
        tokens_out += completion.tokens_out
        latency_ms = int((time.monotonic() - started) * 1000)
        total = Completion(completion.text, tokens_in, tokens_out)
        if schema is None:
            return total, None, latency_ms
        try:
            return total, schema.model_validate_json(completion.text), latency_ms
        except ValidationError as exc:
            if repair_retries == 0:
                raise WastedUsageError(
                    "The model returned output that does not match the schema.",
                    tokens_in,
                    tokens_out,
                    latency_ms,
                ) from exc
            repair_retries -= 1
            conversation = [
                *messages,
                {"role": "assistant", "content": completion.text[:2000]},
                {"role": "user", "content": _repair_prompt(exc)},
            ]


async def _record_usage(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID | None,
    task: str,
    client_id: UUID | None,
    target: _Target,
    completion: Completion,
    latency_ms: int,
) -> Decimal | None:
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
    return cost


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
    if await hard_stop_active(db, tenant_id):
        # Unpriced calls are never added to spend, so they would bypass the hard stop.
        targets = [
            t for t in targets if await _price(db, t.connection.provider, t.model) is not None
        ]
        if not targets:
            raise UnpricedModelError(
                "This model has no known price, so the monthly budget hard stop cannot be "
                "enforced for it. Use a priced model or turn the hard stop off in AI models."
            )
    try:
        return await asyncio.wait_for(
            _run_targets(
                db,
                route=route,
                targets=targets,
                tenant_id=tenant_id,
                user_id=user_id,
                task=task,
                messages=messages,
                client_id=client_id,
                schema=schema,
            ),
            GATEWAY_DEADLINE_SECONDS,
        )
    except asyncio.TimeoutError:
        raise GatewayError(
            "The model did not answer in time. Try again, or choose a faster model."
        ) from None


async def _run_targets(
    db: AsyncSession,
    *,
    route: TaskModelRoute,
    targets: list[_Target],
    tenant_id: UUID,
    user_id: UUID | None,
    task: str,
    messages: list[Message],
    client_id: UUID | None,
    schema: type[BaseModel] | None,
) -> GatewayResult:
    last_error: ProviderError | None = None
    wasted_usage = False
    for target in targets:
        provider = target.connection.provider
        try:
            completion, parsed, latency_ms = await _call(target, route, messages, schema)
        except WastedUsageError as exc:
            last_error = exc
            await _record_usage(
                db, tenant_id, user_id, task, client_id, target,
                Completion("", exc.tokens_in, exc.tokens_out), exc.latency_ms,
            )
            wasted_usage = True
            continue
        except ProviderError as exc:
            last_error = exc
            continue
        cost = await _record_usage(
            db, tenant_id, user_id, task, client_id, target, completion, latency_ms
        )
        return GatewayResult(
            text=completion.text,
            parsed=parsed,
            model=target.model,
            provider=provider,
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
            cost_usd=cost,
        )
    if wasted_usage:
        # The caller will fail the request without committing, but the tokens were spent.
        await db.commit()
    raise GatewayError(str(last_error) if last_error else "The model call failed.")
