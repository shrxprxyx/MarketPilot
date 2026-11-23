"""Tenant monthly budget (FR-BYOM-05). Spend is always aggregated from usage_logs for the
current calendar month (UTC), so it can never drift from the real usage rows. Unpriced
calls (cost NULL) are counted separately and never added to spend."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.usage_log import UsageLog


@dataclass
class BudgetStatus:
    monthly_budget_usd: Decimal | None
    hard_stop: bool
    spent_usd: Decimal
    unpriced_calls: int
    month: str


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


async def _spend(db: AsyncSession, tenant_id: UUID) -> tuple[Decimal, int]:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageLog.cost_usd), 0),
                func.count().filter(UsageLog.cost_usd.is_(None)),
            ).where(UsageLog.tenant_id == tenant_id, UsageLog.created_at >= month_start())
        )
    ).one()
    return Decimal(row[0]), int(row[1])


async def get_budget_status(db: AsyncSession, tenant_id: UUID) -> BudgetStatus:
    tenant = await db.get(Tenant, tenant_id)
    spent, unpriced = await _spend(db, tenant_id)
    return BudgetStatus(
        monthly_budget_usd=tenant.monthly_budget_usd if tenant else None,
        hard_stop=bool(tenant and tenant.hard_stop),
        spent_usd=spent,
        unpriced_calls=unpriced,
        month=datetime.now(timezone.utc).strftime("%Y-%m"),
    )


async def hard_stop_active(db: AsyncSession, tenant_id: UUID) -> bool:
    """True when the tenant has a monthly budget with the hard stop switched on."""
    tenant = await db.get(Tenant, tenant_id)
    return bool(tenant and tenant.monthly_budget_usd is not None and tenant.hard_stop)


async def hard_stop_reached(db: AsyncSession, tenant_id: UUID) -> bool:
    """Cheap pre-call check: tenants without a hard-stopped budget never pay for the
    spend aggregate. The check happens before the call and the call's own cost is only known
    afterwards, so the call that crosses the limit, and any requests already in flight when
    it is crossed, can overshoot the budget slightly. The next call is refused."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.monthly_budget_usd is None or not tenant.hard_stop:
        return False
    spent, _ = await _spend(db, tenant_id)
    return spent >= tenant.monthly_budget_usd
