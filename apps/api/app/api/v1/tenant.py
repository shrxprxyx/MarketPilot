"""Agency settings and white-label branding (FR-TEN-07, SRS §2.2: admin only to change;
every member can read, since the app shell shows the agency name)."""
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.request import client_ip
from app.db.session import get_db
from app.models.tenant import Tenant

router = APIRouter(prefix="/tenant", tags=["tenant"])

DB = Annotated[AsyncSession, Depends(get_db)]
ADMIN = require_role("admin")

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class BrandingOut(BaseModel):
    logo_url: str | None
    primary_color: str | None
    report_footer: str | None


class TenantDetailOut(BaseModel):
    id: UUID
    name: str
    slug: str
    plan: str
    branding: BrandingOut


class TenantPatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank.")
        return v


class BrandingIn(BaseModel):
    """A full replacement (PUT): omitted fields clear the stored value."""

    logo_url: str | None = Field(default=None, max_length=500)
    primary_color: str | None = None
    report_footer: str | None = Field(default=None, max_length=300)

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        # The logo is rendered into reports and <img> tags, so only web URLs are allowed
        # (no javascript:, data: or file: schemes).
        if not re.match(r"^https?://[^\s]+$", v, re.IGNORECASE):
            raise ValueError("Logo URL must start with http:// or https://")
        return v

    @field_validator("primary_color")
    @classmethod
    def _color(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _HEX_COLOR.match(v):
            raise ValueError("Primary color must be a hex value like #1f6f43.")
        return v.lower()

    @field_validator("report_footer")
    @classmethod
    def _footer(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


def _out(t: Tenant) -> TenantDetailOut:
    return TenantDetailOut(
        id=t.id,
        name=t.name,
        slug=t.slug,
        plan=t.plan,
        branding=BrandingOut(
            logo_url=t.logo_url, primary_color=t.primary_color, report_footer=t.report_footer
        ),
    )


async def _get_tenant(db: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise ProblemException(404, "Not Found", "Tenant not found.")
    return tenant


@router.get("", response_model=TenantDetailOut)
async def get_tenant(
    current: Annotated[CurrentUser, Depends(get_current_user)], db: DB
) -> TenantDetailOut:
    return _out(await _get_tenant(db, current.tenant_id))


@router.patch("", response_model=TenantDetailOut)
async def update_tenant(
    body: TenantPatch, request: Request, current: Annotated[CurrentUser, ADMIN], db: DB
) -> TenantDetailOut:
    tenant = await _get_tenant(db, current.tenant_id)
    old = tenant.name
    tenant.name = body.name
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="tenant.updated",
        entity="tenant",
        entity_id=tenant.id,
        meta={"name_from": old, "name_to": body.name},
        ip=client_ip(request),
    )
    await db.commit()
    return _out(tenant)


@router.put("/branding", response_model=TenantDetailOut)
async def put_branding(
    body: BrandingIn, request: Request, current: Annotated[CurrentUser, ADMIN], db: DB
) -> TenantDetailOut:
    tenant = await _get_tenant(db, current.tenant_id)
    tenant.logo_url = body.logo_url
    tenant.primary_color = body.primary_color
    tenant.report_footer = body.report_footer
    log_audit(
        db,
        tenant_id=current.tenant_id,
        actor_id=current.user.id,
        action="tenant.branding_updated",
        entity="tenant",
        entity_id=tenant.id,
        ip=client_ip(request),
    )
    await db.commit()
    return _out(tenant)
