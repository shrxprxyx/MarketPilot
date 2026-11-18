import hashlib
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import (
    create_access_token,
    make_refresh_token,
    refresh_token_expiry,
)
from app.auth.password import hash_password, verify_password
from app.core.errors import problem
from app.db.session import get_db
from app.models.membership import Membership
from app.models.refresh_token import RefreshToken
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

DB = Annotated[AsyncSession, Depends(get_db)]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
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


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: RegisterIn, db: DB) -> TokenOut:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing:
        raise problem(409, "Conflict", "Email already registered.")  # type: ignore[misc]

    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)

    tenant = Tenant(name=body.tenant_name, slug=body.tenant_name.lower().replace(" ", "-"))
    db.add(tenant)

    await db.flush()  # get ids before membership

    membership = Membership(user_id=user.id, tenant_id=tenant.id, role="owner")
    db.add(membership)

    raw = make_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=refresh_token_expiry(),
    )
    db.add(rt)
    await db.commit()

    access = create_access_token(user.id, tenant.id, "owner")
    return TokenOut(access_token=access, refresh_token=raw)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: DB) -> TokenOut:
    user = await db.scalar(select(User).where(User.email == body.email))
    if not user or not verify_password(body.password, user.hashed_password):
        raise problem(401, "Unauthorized", "Invalid credentials.")  # type: ignore[misc]

    membership = await db.scalar(
        select(Membership).where(Membership.user_id == user.id)
    )
    if not membership:
        raise problem(403, "Forbidden", "No tenant membership found.")  # type: ignore[misc]

    raw = make_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=refresh_token_expiry(),
    )
    db.add(rt)
    await db.commit()

    access = create_access_token(user.id, membership.tenant_id, membership.role)
    return TokenOut(access_token=access, refresh_token=raw)


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, db: DB) -> TokenOut:
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    rt = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    if not rt or rt.revoked or rt.expires_at < datetime.now(timezone.utc):
        raise problem(401, "Unauthorized", "Invalid or expired refresh token.")  # type: ignore[misc]

    # rotate: revoke old, issue new
    rt.revoked = True
    raw = make_refresh_token()
    new_rt = RefreshToken(
        user_id=rt.user_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=refresh_token_expiry(),
    )
    db.add(new_rt)

    membership = await db.scalar(
        select(Membership).where(Membership.user_id == rt.user_id)
    )
    if not membership:
        raise problem(403, "Forbidden", "No tenant membership found.")  # type: ignore[misc]

    await db.commit()
    access = create_access_token(rt.user_id, membership.tenant_id, membership.role)
    return TokenOut(access_token=access, refresh_token=raw)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn, db: DB) -> None:
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    rt = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if rt:
        rt.revoked = True
        await db.commit()