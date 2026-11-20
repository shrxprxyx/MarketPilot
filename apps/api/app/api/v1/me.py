from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.membership import Membership
from app.models.tenant import Tenant

router = APIRouter(prefix="/me", tags=["me"])

DB = Annotated[AsyncSession, Depends(get_db)]


class MeOut(BaseModel):
    user_id: UUID
    tenant_id: UUID
    role: str
    email: str
    tenant_name: str


class TenantOut(BaseModel):
    id: UUID
    name: str
    role: str


@router.get("", response_model=MeOut)
async def get_me(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
) -> MeOut:
    tenant_name = await db.scalar(select(Tenant.name).where(Tenant.id == current.tenant_id))
    return MeOut(
        user_id=current.user.id,
        tenant_id=current.tenant_id,
        role=current.role,
        email=current.user.email,
        # The membership was just verified in get_current_user, so the tenant exists.
        tenant_name=tenant_name or "",
    )


@router.get("/tenants", response_model=list[TenantOut])
async def list_my_tenants(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
) -> list[TenantOut]:
    """Every agency the caller has an active membership in (for the web app's
    switcher). The memberships RLS policy lets a caller read their own rows across
    tenants via app.user_id; `tenants` itself has no RLS, so the join is safe."""
    rows = await db.execute(
        select(Tenant.id, Tenant.name, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == current.user.id, Membership.status == "active")
        .order_by(Membership.created_at, Tenant.id)
    )
    return [TenantOut(id=r.id, name=r.name, role=r.role) for r in rows.all()]
