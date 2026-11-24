import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.jwt import (
    create_access_token,
    make_refresh_token,
    refresh_token_expiry,
)
from app.auth.password import hash_password, verify_password
from app.auth.rate_limit import (
    clear_login_attempts,
    enforce_login_rate_limit,
    record_login_failure,
)
from app.auth.stream_ticket import TTL_SECONDS, issue_ticket
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.rate_limit import rate_limit
from app.core.request import client_ip
from app.db.rls import set_rls_context
from app.db.session import get_db
from app.models.invite import Invite
from app.models.membership import Membership
from app.models.refresh_token import RefreshToken
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

DB = Annotated[AsyncSession, Depends(get_db)]

# First member of a freshly registered tenant. Matches the SRS role vocabulary
# (admin | manager | member); "admin" has full control of the tenant.
OWNER_ROLE = "admin"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    tenant_name: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class AcceptInviteIn(BaseModel):
    token: str
    # Sets the password for a brand-new account, or must match the existing one
    # if this email is already registered (see accept_invite for why one field
    # covers both cases).
    password: str = Field(min_length=10)


class SwitchTenantIn(BaseModel):
    tenant_id: UUID


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: RegisterIn, request: Request, db: DB) -> TokenOut:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise ProblemException(409, "Conflict", "Email already registered.")

    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)

    tenant = Tenant(name=body.tenant_name, slug=body.tenant_name.lower().replace(" ", "-"))
    db.add(tenant)

    await db.flush()

    # Both sides of the bridge row are known now, so set RLS context before the
    # membership insert — memberships is FORCE RLS and needs a matching tenant_id
    # or user_id to satisfy its WITH CHECK clause.
    await set_rls_context(db, tenant_id=tenant.id, user_id=user.id)

    membership = Membership(user_id=user.id, tenant_id=tenant.id, role=OWNER_ROLE)
    db.add(membership)

    raw = make_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        tenant_id=tenant.id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=refresh_token_expiry(),
    )
    db.add(rt)

    log_audit(
        db,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="register",
        entity="tenant",
        entity_id=tenant.id,
        meta={"email": user.email},
        ip=client_ip(request),
    )
    await db.commit()

    access = create_access_token(user.id, tenant.id, OWNER_ROLE)
    return TokenOut(access_token=access, refresh_token=raw)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, db: DB) -> TokenOut:
    ip = client_ip(request)
    await enforce_login_rate_limit(body.email, ip)

    user = await db.scalar(select(User).where(User.email == body.email))
    if not user or not verify_password(body.password, user.hashed_password):
        await record_login_failure(body.email, ip)
        raise ProblemException(401, "Unauthorized", "Invalid credentials.")

    # We know the user but not yet which tenant to act as — memberships' policy
    # lets a row through on user_id alone so this lookup can resolve that. A user
    # can belong to several tenants (FR-AUTH-05), so login picks the oldest active
    # one as a deterministic default; switch-tenant moves to any other afterward.
    await set_rls_context(db, user_id=user.id)

    membership = await db.scalar(
        select(Membership)
        .where(Membership.user_id == user.id, Membership.status == "active")
        .order_by(Membership.created_at.asc())
        .limit(1)
    )
    if not membership:
        raise ProblemException(403, "Forbidden", "No active tenant membership found.")

    await clear_login_attempts(body.email, ip)

    raw = make_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        tenant_id=membership.tenant_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=refresh_token_expiry(),
    )
    db.add(rt)

    # Only app.user_id was set above (tenant wasn't chosen yet) — audit_log's
    # INSERT policy needs app.tenant_id too, now that we know which one.
    await set_rls_context(db, tenant_id=membership.tenant_id)
    log_audit(
        db,
        tenant_id=membership.tenant_id,
        actor_id=user.id,
        action="login",
        entity="user",
        entity_id=user.id,
        ip=ip,
    )
    await db.commit()

    access = create_access_token(user.id, membership.tenant_id, membership.role)
    return TokenOut(access_token=access, refresh_token=raw)


# A browser can legitimately send the same refresh cookie twice (two tabs, or a reload racing
# a request already in flight). A token rotated within this window is that race, not theft.
REUSE_GRACE = timedelta(seconds=10)


async def _revoke_chain(db: AsyncSession, token: RefreshToken) -> None:
    """Revoke every token rotated from `token`, so a stolen-and-replayed token kills the session."""
    next_id = token.replaced_by
    while next_id is not None:
        successor = await db.get(RefreshToken, next_id)
        if successor is None:
            break
        successor.revoked = True
        next_id = successor.replaced_by


async def _chain_tail(db: AsyncSession, token: RefreshToken) -> RefreshToken:
    """The newest token rotated from `token` (itself if it was never rotated)."""
    tail = token
    while tail.replaced_by is not None:
        nxt = await db.get(RefreshToken, tail.replaced_by)
        if nxt is None:
            break
        tail = nxt
    return tail


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, db: DB) -> TokenOut:
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    # FOR UPDATE makes two simultaneous refreshes with one token take turns instead of
    # both rotating it and forking the chain.
    rt = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )

    if rt and rt.revoked and rt.replaced_by is not None:
        if datetime.now(timezone.utc) - rt.updated_at > REUSE_GRACE:
            # A long-rotated token was presented again: treat the chain as stolen.
            await _revoke_chain(db, rt)
            await db.commit()
            raise ProblemException(401, "Unauthorized", "Invalid or expired refresh token.")
        # Just rotated: this is the double-send race. Carry on from the newest token so the
        # session survives and the chain stays a single line.
        rt = await _chain_tail(db, rt)

    if not rt or rt.revoked or rt.expires_at < datetime.now(timezone.utc):
        raise ProblemException(401, "Unauthorized", "Invalid or expired refresh token.")

    tenant_id = rt.tenant_id
    rt.revoked = True
    raw = make_refresh_token()
    new_rt = RefreshToken(
        user_id=rt.user_id,
        tenant_id=tenant_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=refresh_token_expiry(),
    )
    db.add(new_rt)
    await db.flush()
    rt.replaced_by = new_rt.id

    # Resume the exact tenant this token was issued for — no re-resolution, so
    # this stays correct for users with several active memberships.
    await set_rls_context(db, tenant_id=tenant_id, user_id=rt.user_id)

    membership = await db.scalar(
        select(Membership).where(
            Membership.user_id == rt.user_id,
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
        )
    )
    if not membership:
        raise ProblemException(403, "Forbidden", "No active tenant membership found.")

    await db.commit()
    access = create_access_token(rt.user_id, tenant_id, membership.role)
    return TokenOut(access_token=access, refresh_token=raw)


@router.post("/switch-tenant", response_model=TokenOut)
async def switch_tenant(
    body: SwitchTenantIn,
    request: Request,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: DB,
) -> TokenOut:
    """FR-AUTH-05: re-issue a token pair scoped to a different tenant the caller
    is an active member of. `get_current_user` already set app.user_id, so the
    membership policy's user_id branch lets this find any of the caller's rows
    regardless of which tenant_id is being switched to.
    """
    membership = await db.scalar(
        select(Membership).where(
            Membership.user_id == current.user.id,
            Membership.tenant_id == body.tenant_id,
            Membership.status == "active",
        )
    )
    if not membership:
        raise ProblemException(403, "Forbidden", "Not an active member of that tenant.")

    raw = make_refresh_token()
    rt = RefreshToken(
        user_id=current.user.id,
        tenant_id=body.tenant_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=refresh_token_expiry(),
    )
    db.add(rt)

    # audit_log's INSERT policy checks tenant_id against app.tenant_id, which
    # get_current_user left set to the *original* tenant — move it to the target
    # before writing a row scoped to the target.
    await set_rls_context(db, tenant_id=body.tenant_id)
    log_audit(
        db,
        tenant_id=body.tenant_id,
        actor_id=current.user.id,
        action="tenant.switch",
        entity="tenant",
        entity_id=body.tenant_id,
        meta={"from_tenant_id": str(current.tenant_id)},
        ip=client_ip(request),
    )
    await db.commit()

    access = create_access_token(current.user.id, body.tenant_id, membership.role)
    return TokenOut(access_token=access, refresh_token=raw)


@router.post("/accept-invite", response_model=TokenOut)
async def accept_invite(body: AcceptInviteIn, request: Request, db: DB) -> TokenOut:
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    # Nothing about the caller's tenant or identity is known yet — the invite
    # row is reachable only through the token-hash branch of its RLS policy
    # (see app/db/rls.py and migration f3c679dd395a).
    await set_rls_context(db, invite_token_hash=token_hash)

    invite = await db.scalar(select(Invite).where(Invite.token_hash == token_hash))
    if not invite or invite.status != "pending" or invite.expires_at < datetime.now(timezone.utc):
        raise ProblemException(401, "Unauthorized", "Invalid or expired invite.")

    tenant_id = invite.tenant_id
    role = invite.role
    invited_by = invite.invited_by

    user = await db.scalar(select(User).where(User.email == invite.email))
    if user is None:
        user = User(email=invite.email, hashed_password=hash_password(body.password))
        db.add(user)
        await db.flush()
    elif not verify_password(body.password, user.hashed_password):
        # Existing account: `password` must authenticate it, not set a new one.
        raise ProblemException(401, "Unauthorized", "Incorrect password for existing account.")

    await set_rls_context(db, tenant_id=tenant_id, user_id=user.id, invite_token_hash=token_hash)

    already_member = await db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant_id)
    )
    if already_member:
        raise ProblemException(409, "Conflict", "Already a member of this tenant.")

    membership = Membership(user_id=user.id, tenant_id=tenant_id, role=role, invited_by=invited_by)
    db.add(membership)
    await db.delete(invite)  # one-time use

    raw = make_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        tenant_id=tenant_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=refresh_token_expiry(),
    )
    db.add(rt)

    log_audit(
        db,
        tenant_id=tenant_id,
        actor_id=user.id,
        action="invite.accepted",
        entity="membership",
        entity_id=membership.id,
        meta={"role": role, "invited_by": str(invited_by) if invited_by else None},
        ip=client_ip(request),
    )
    await db.commit()

    access = create_access_token(user.id, tenant_id, role)
    return TokenOut(access_token=access, refresh_token=raw)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn, request: Request, db: DB) -> None:
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    rt = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if rt:
        already_revoked = rt.revoked
        rt.revoked = True
        if not already_revoked:
            # audit_log's INSERT policy needs the tenant of the session being ended.
            await set_rls_context(db, tenant_id=rt.tenant_id, user_id=rt.user_id)
            log_audit(
                db,
                tenant_id=rt.tenant_id,
                actor_id=rt.user_id,
                action="logout",
                entity="user",
                entity_id=rt.user_id,
                ip=client_ip(request),
            )
        await db.commit()


class StreamTicketOut(BaseModel):
    ticket: str
    expires_in: int


@router.post(
    "/stream-ticket",
    response_model=StreamTicketOut,
    dependencies=[rate_limit("auth.stream_ticket", user=60, tenant=300)],
)
async def stream_ticket(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> StreamTicketOut:
    """A 60-second, single-use ticket for opening an SSE or WebSocket stream, which cannot
    carry an Authorization header (SRS §11)."""
    ticket = await issue_ticket(current.user.id, current.tenant_id)
    return StreamTicketOut(ticket=ticket, expires_in=TTL_SECONDS)
