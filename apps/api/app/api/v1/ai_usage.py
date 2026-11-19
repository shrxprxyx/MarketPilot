from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, require_role
from app.db.session import get_db
from app.models.usage_log import UsageLog

router = APIRouter(prefix="/ai/usage", tags=["ai"])

DB = Annotated[AsyncSession, Depends(get_db)]
# §2.2: admins and managers view usage and cost analytics.
VIEWER = require_role("admin", "manager")


class UsageRow(BaseModel):
    key: str | None
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal  # sum of priced calls; unpriced calls count as 0
    unpriced_calls: int


@router.get("", response_model=list[UsageRow])
async def usage(
    current: Annotated[CurrentUser, VIEWER],
    db: DB,
    group_by: Literal["day", "client", "task", "model"] = "day",
    days: Annotated[int, Query(ge=1, le=366)] = 30,
) -> list[UsageRow]:
    """FR-BYOM-04: usage grouped by day, client, task or model."""
    group_col = {
        "day": func.to_char(func.date_trunc("day", UsageLog.created_at), "YYYY-MM-DD"),
        "client": UsageLog.client_id,
        "task": UsageLog.task_type,
        "model": UsageLog.model,
    }[group_by]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt: Select[tuple[object, int, int, int, Decimal, int]] = (
        select(
            group_col,
            func.count(),
            func.coalesce(func.sum(UsageLog.tokens_in), 0),
            func.coalesce(func.sum(UsageLog.tokens_out), 0),
            func.coalesce(func.sum(UsageLog.cost_usd), 0),
            func.count().filter(UsageLog.cost_usd.is_(None)),
        )
        .where(UsageLog.tenant_id == current.tenant_id, UsageLog.created_at >= since)
        .group_by(group_col)
        .order_by(group_col.desc() if group_by == "day" else func.count().desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        UsageRow(
            key=None if r[0] is None else str(r[0]),
            calls=r[1],
            tokens_in=int(r[2]),
            tokens_out=int(r[3]),
            cost_usd=Decimal(r[4]),
            unpriced_calls=r[5],
        )
        for r in rows
    ]
