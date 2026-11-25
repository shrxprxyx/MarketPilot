from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, require_role
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.request import client_ip
from app.db.session import get_db
from app.models.ai_connection import AIConnection
from app.models.task_model_route import TaskModelRoute

router = APIRouter(prefix="/ai/routes", tags=["ai"])

DB = Annotated[AsyncSession, Depends(get_db)]
# §2.2: admins and managers manage per-task model routing.
WRITER = require_role("admin", "manager")

TaskType = Literal["strategy", "content", "analysis", "embedding_summary"]


class RouteIn(BaseModel):
    task_type: TaskType
    connection_id: UUID
    model: str = Field(min_length=1, max_length=200)
    # Unset means the task's default: 0.3 for analysis (repeatable), 0.7 otherwise (SRS §10.4).
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=200_000)
    fallback_connection_id: UUID | None = None
    fallback_model: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _fallback_pair(self) -> "RouteIn":
        if self.temperature is None:
            self.temperature = 0.3 if self.task_type == "analysis" else 0.7
        if (self.fallback_connection_id is None) != (self.fallback_model is None):
            raise ValueError("fallback_connection_id and fallback_model go together")
        return self


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_type: str
    connection_id: UUID
    model: str
    temperature: float
    max_tokens: int
    fallback_connection_id: UUID | None
    fallback_model: str | None


@router.get("", response_model=list[RouteOut])
async def list_routes(current: Annotated[CurrentUser, WRITER], db: DB) -> list[TaskModelRoute]:
    rows = await db.scalars(
        select(TaskModelRoute)
        .where(TaskModelRoute.tenant_id == current.tenant_id)
        .order_by(TaskModelRoute.task_type)
    )
    return list(rows)


@router.put("", response_model=list[RouteOut])
async def put_routes(
    body: list[RouteIn], request: Request, current: Annotated[CurrentUser, WRITER], db: DB
) -> list[TaskModelRoute]:
    """Upserts one route per task type; task types not in the body are untouched."""
    if len({r.task_type for r in body}) != len(body):
        raise ProblemException(422, "Unprocessable Entity", "Duplicate task_type in request.")

    wanted = {r.connection_id for r in body} | {
        r.fallback_connection_id for r in body if r.fallback_connection_id
    }
    owned = set(
        await db.scalars(
            select(AIConnection.id).where(
                AIConnection.tenant_id == current.tenant_id, AIConnection.id.in_(wanted)
            )
        )
    )
    if wanted - owned:
        raise ProblemException(404, "Not Found", "AI connection not found.")

    existing = {
        r.task_type: r
        for r in await db.scalars(
            select(TaskModelRoute).where(TaskModelRoute.tenant_id == current.tenant_id)
        )
    }
    result: list[TaskModelRoute] = []
    for item in body:
        route = existing.get(item.task_type)
        if route is None:
            route = TaskModelRoute(tenant_id=current.tenant_id, task_type=item.task_type)
            db.add(route)
        for field, value in item.model_dump(exclude={"task_type"}).items():
            setattr(route, field, value)
        result.append(route)

    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="ai_route.updated",
        entity="ai_route",
        meta={"tasks": [r.task_type for r in body]},
        ip=client_ip(request),
    )
    await db.commit()
    return result
