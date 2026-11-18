import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, require_role
from app.auth.jwt import invite_token_expiry, make_invite_token
from app.core.errors import ProblemException
from app.db.session import get_db
from app.models.invite import Invite
from app.models.membership import Membership
from app.models.user import User

router = APIRouter(prefix="/members", tags=["members"])

DB = Annotated[AsyncSession, Depends(get_db)]
# FR-TEN-01: "Admins list members, change roles, deactivate members" — admin-only,
# unlike clients (FR-TEN-02) where managers can write too.
ADMIN = require_role("admin")

Role = Literal["admin", "manager", "member"]
Status = Literal["active", "deactivated"]


class MemberOut(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    role: str
    status: str
    created_at: datetime


class MemberPatch(BaseModel):
    role: Role | None = None
    status: Status | None = None


class InviteIn(BaseModel):
    email: EmailStr
    role: Role


class InviteOut(BaseModel):
    id: UUID
    email: str
    role: str
    # Shown once, here, so the admin can copy it — FR-AUTH-04 ("the invitation
    # link is also shown in the UI"). Only the hash is ever stored, so this is
    # the one and only time the raw token is retrievable.
    invite_token: str
    expires_at: datetime


class PendingInviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    expires_at: datetime
    created_at: datetime


async def _get_membership_or_404(
    db: AsyncSession, current: CurrentUser, membership_id: UUID
) -> Membership:
    membership = await db.scalar(
        select(Membership).where(
            Membership.id == membership_id, Membership.tenant_id == current.tenant_id
        )
    )
    if not membership:
        raise ProblemException(404, "Not Found", "Member not found.")
    return membership


async def _is_last_active_admin(db: AsyncSession, tenant_id: UUID, membership: Membership) -> bool:
    if membership.role != "admin" or membership.status != "active":
        return False
    other_active_admins = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.role == "admin",
            Membership.status == "active",
            Membership.id != membership.id,
        )
    )
    return other_active_admins == 0


@router.get("", response_model=list[MemberOut])
async def list_members(
    current: Annotated[CurrentUser, ADMIN],
    db: DB,
) -> list[MemberOut]:
    rows = (
        await db.execute(
            select(Membership, User.email)
            .join(User, User.id == Membership.user_id)
            .where(Membership.tenant_id == current.tenant_id)
            .order_by(Membership.created_at.asc())
        )
    ).all()
    return [
        MemberOut(
            id=m.id,
            user_id=m.user_id,
            email=email,
            role=m.role,
            status=m.status,
            created_at=m.created_at,
        )
        for m, email in rows
    ]


@router.patch("/{membership_id}", response_model=MemberOut)
async def update_member(
    membership_id: UUID,
    body: MemberPatch,
    current: Annotated[CurrentUser, ADMIN],
    db: DB,
) -> MemberOut:
    membership = await _get_membership_or_404(db, current, membership_id)

    demoting = body.role is not None and body.role != "admin"
    deactivating = body.status is not None and body.status != "active"
    if (demoting or deactivating) and await _is_last_active_admin(
        db, current.tenant_id, membership
    ):
        raise ProblemException(
            409, "Conflict", "The last admin of a tenant cannot be demoted or deactivated."
        )

    if body.role is not None:
        membership.role = body.role
    if body.status is not None:
        membership.status = body.status
    await db.commit()

    email = await db.scalar(select(User.email).where(User.id == membership.user_id))
    return MemberOut(
        id=membership.id,
        user_id=membership.user_id,
        email=email or "",
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
    )


@router.delete("/{membership_id}", status_code=204)
async def remove_member(
    membership_id: UUID,
    current: Annotated[CurrentUser, ADMIN],
    db: DB,
) -> None:
    membership = await _get_membership_or_404(db, current, membership_id)
    if await _is_last_active_admin(db, current.tenant_id, membership):
        raise ProblemException(409, "Conflict", "The last admin of a tenant cannot be removed.")

    await db.delete(membership)
    await db.commit()


@router.post("/invite", response_model=InviteOut, status_code=201)
async def create_invite(
    body: InviteIn,
    current: Annotated[CurrentUser, ADMIN],
    db: DB,
) -> InviteOut:
    existing = await db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == current.tenant_id, User.email == body.email)
    )
    if existing:
        raise ProblemException(
            409,
            "Conflict",
            "This email already has a membership in this tenant — "
            "update it instead of inviting again.",
        )

    raw = make_invite_token()
    invite = Invite(
        tenant_id=current.tenant_id,
        email=body.email,
        role=body.role,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        invited_by=current.user.id,
        expires_at=invite_token_expiry(),
    )
    db.add(invite)
    await db.commit()

    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        invite_token=raw,
        expires_at=invite.expires_at,
    )


@router.get("/invites", response_model=list[PendingInviteOut])
async def list_invites(
    current: Annotated[CurrentUser, ADMIN],
    db: DB,
) -> list[PendingInviteOut]:
    rows = (
        await db.execute(
            select(Invite)
            .where(Invite.tenant_id == current.tenant_id, Invite.status == "pending")
            .order_by(Invite.created_at.desc())
        )
    ).scalars().all()
    return [PendingInviteOut.model_validate(i) for i in rows]


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: UUID,
    current: Annotated[CurrentUser, ADMIN],
    db: DB,
) -> None:
    invite = await db.scalar(
        select(Invite).where(Invite.id == invite_id, Invite.tenant_id == current.tenant_id)
    )
    if not invite:
        raise ProblemException(404, "Not Found", "Invite not found.")
    await db.delete(invite)
    await db.commit()
