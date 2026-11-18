from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.core.errors import ProblemException
from app.core.pagination import decode_cursor, encode_cursor
from app.db.session import get_db
from app.models.brand_profile import BrandProfile
from app.models.client import Client

router = APIRouter(prefix="/clients", tags=["clients"])

DB = Annotated[AsyncSession, Depends(get_db)]
# FR-TEN-02/03: admins and managers manage clients and brand profiles; members
# only read them (§2.2 capability matrix).
WRITER = require_role("admin", "manager")


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website_url: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=120)
    goals: list[str] | None = None


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    website_url: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=120)
    goals: list[str] | None = None
    status: Literal["active", "archived"] | None = None


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    website_url: str | None
    industry: str | None
    goals: list[str] | None
    status: str


class ClientListOut(BaseModel):
    items: list[ClientOut]
    next_cursor: str | None


class BrandProfileIn(BaseModel):
    voice: str | None = Field(default=None, max_length=120)
    tone: str | None = Field(default=None, max_length=120)
    audience: str | None = None
    keywords: list[str] | None = None
    do_rules: list[str] | None = None
    dont_rules: list[str] | None = None
    sample_text: str | None = None


class BrandProfileOut(BrandProfileIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID


async def _get_client_or_404(db: AsyncSession, current: CurrentUser, client_id: UUID) -> Client:
    # Explicit tenant_id filter here is defense-in-depth on top of RLS (§3.4) —
    # the query should never depend on RLS alone to stay tenant-scoped.
    client = await db.scalar(
        select(Client).where(Client.id == client_id, Client.tenant_id == current.tenant_id)
    )
    if not client:
        raise ProblemException(404, "Not Found", "Client not found.")
    return client


@router.post("", response_model=ClientOut, status_code=201)
async def create_client(
    body: ClientIn,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> Client:
    client = Client(
        tenant_id=current.tenant_id,
        name=body.name,
        website_url=body.website_url,
        industry=body.industry,
        goals=body.goals,
    )
    db.add(client)
    await db.commit()
    return client


@router.get("", response_model=ClientListOut)
async def list_clients(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> ClientListOut:
    stmt = (
        select(Client)
        .where(Client.tenant_id == current.tenant_id)
        .order_by(Client.created_at.desc(), Client.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        try:
            created_at, row_id = decode_cursor(cursor)
        except ValueError as exc:
            raise ProblemException(400, "Bad Request", "Invalid cursor.") from exc
        stmt = stmt.where(tuple_(Client.created_at, Client.id) < (created_at, row_id))

    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    )
    return ClientListOut(
        items=[ClientOut.model_validate(c) for c in items], next_cursor=next_cursor
    )


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
) -> Client:
    return await _get_client_or_404(db, current, client_id)


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: UUID,
    body: ClientPatch,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> Client:
    client = await _get_client_or_404(db, current, client_id)
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(client, field, value)
    await db.commit()
    return client


@router.delete("/{client_id}", status_code=204)
async def archive_client(
    client_id: UUID,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> None:
    """Archives the client (soft delete) rather than removing the row — audit
    history (FR-AUD-08) and anything already linked to it must survive."""
    client = await _get_client_or_404(db, current, client_id)
    client.status = "archived"
    await db.commit()


@router.get("/{client_id}/brand-profile", response_model=BrandProfileOut)
async def get_brand_profile(
    client_id: UUID,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
) -> BrandProfile:
    await _get_client_or_404(db, current, client_id)
    profile = await db.scalar(
        select(BrandProfile).where(
            BrandProfile.client_id == client_id, BrandProfile.tenant_id == current.tenant_id
        )
    )
    if not profile:
        raise ProblemException(404, "Not Found", "Brand profile not set for this client.")
    return profile


@router.put("/{client_id}/brand-profile", response_model=BrandProfileOut)
async def upsert_brand_profile(
    client_id: UUID,
    body: BrandProfileIn,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> BrandProfile:
    await _get_client_or_404(db, current, client_id)
    profile = await db.scalar(
        select(BrandProfile).where(
            BrandProfile.client_id == client_id, BrandProfile.tenant_id == current.tenant_id
        )
    )
    if profile is None:
        profile = BrandProfile(tenant_id=current.tenant_id, client_id=client_id)
        db.add(profile)
    for field, value in body.model_dump().items():
        setattr(profile, field, value)
    await db.commit()
    return profile
