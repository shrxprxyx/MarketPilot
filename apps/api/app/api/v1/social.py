"""Social accounts, performance-export import and metrics (FR-AUD-09, 10). Admins and managers
change data (§2.2); every role can read it."""
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.core.audit import log_audit
from app.core.errors import ProblemException
from app.core.request import client_ip
from app.db.session import get_db
from app.models.client import Client
from app.models.social import PLATFORMS, SocialAccount, SocialDaily, SocialPost
from app.social.importer import POST_COUNTS, ImportFileError, parse_export, template
from app.social.metrics import compute_metrics

router = APIRouter(tags=["social"])
DB = Annotated[AsyncSession, Depends(get_db)]
WRITER = require_role("admin", "manager")
Platform = Literal["facebook", "instagram", "linkedin"]
PREVIEW_ROWS = 10


class AccountIn(BaseModel):
    platform: Platform
    handle: str = Field(min_length=1, max_length=200)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    platform: str
    handle: str
    created_at: datetime


class ImportIn(BaseModel):
    kind: Literal["posts", "daily"] = "posts"
    format: Literal["csv", "json"]
    content: str = Field(min_length=1)
    commit: bool = False  # false only validates and previews


class ImportOut(BaseModel):
    committed: bool
    total: int
    valid: int
    errors: list[dict[str, Any]]
    sample: list[dict[str, Any]]


async def _client_or_404(db: AsyncSession, current: CurrentUser, client_id: UUID) -> Client:
    client = await db.scalar(
        select(Client).where(Client.id == client_id, Client.tenant_id == current.tenant_id)
    )
    if client is None:
        raise ProblemException(404, "Not Found", "Client not found.")
    return client


async def _account_or_404(
    db: AsyncSession, current: CurrentUser, account_id: UUID
) -> SocialAccount:
    account = await db.scalar(
        select(SocialAccount).where(
            SocialAccount.id == account_id, SocialAccount.tenant_id == current.tenant_id
        )
    )
    if account is None:
        raise ProblemException(404, "Not Found", "Social account not found.")
    return account


@router.get("/social-templates")
async def templates(
    _: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """The columns each platform's export is read with; the first name of each is the one shown."""
    return {
        "posts": {p: {k: v for k, v in template(p, "posts").items()} for p in PLATFORMS},
        "daily": template("facebook", "daily"),
    }


@router.post("/clients/{client_id}/social-accounts", response_model=AccountOut, status_code=201)
async def add_account(
    client_id: UUID,
    body: AccountIn,
    request: Request,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> AccountOut:
    client = await _client_or_404(db, current, client_id)
    if client.status == "archived":
        raise ProblemException(409, "Conflict", "Restore this client first.")
    account = SocialAccount(
        tenant_id=current.tenant_id,
        client_id=client_id,
        platform=body.platform,
        handle=body.handle.strip().lstrip("@"),
    )
    db.add(account)
    try:
        await db.flush()
    except IntegrityError:
        raise ProblemException(
            409, "Conflict", "This account is already added for the client."
        ) from None
    log_audit(
        db, tenant_id=current.tenant_id, actor_id=current.user.id,
        action="social_account.added", entity="social_account", entity_id=account.id,
        meta={"client_id": str(client_id), "platform": account.platform}, ip=client_ip(request),
    )
    await db.commit()
    return AccountOut.model_validate(account)


@router.get("/clients/{client_id}/social-accounts", response_model=list[AccountOut])
async def list_accounts(
    client_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], db: DB
) -> list[AccountOut]:
    await _client_or_404(db, current, client_id)
    rows = await db.scalars(
        select(SocialAccount)
        .where(SocialAccount.client_id == client_id, SocialAccount.tenant_id == current.tenant_id)
        .order_by(SocialAccount.platform, SocialAccount.handle)
    )
    return [AccountOut.model_validate(r) for r in rows]


@router.delete("/social-accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: UUID, request: Request, current: Annotated[CurrentUser, WRITER], db: DB
) -> None:
    account = await _account_or_404(db, current, account_id)
    log_audit(
        db, tenant_id=current.tenant_id, actor_id=current.user.id,
        action="social_account.deleted", entity="social_account", entity_id=account.id,
        meta={"client_id": str(account.client_id), "platform": account.platform},
        ip=client_ip(request),
    )
    await db.delete(account)  # its posts and daily rows go with it (ON DELETE CASCADE)
    await db.commit()


@router.post(
    "/social-accounts/{account_id}/import",
    response_model=ImportOut,
)
async def import_export(
    account_id: UUID,
    body: ImportIn,
    request: Request,
    current: Annotated[CurrentUser, WRITER],
    db: DB,
) -> ImportOut:
    account = await _account_or_404(db, current, account_id)
    try:
        parsed = parse_export(account.platform, body.kind, body.format, body.content)
    except ImportFileError as exc:
        raise ProblemException(422, "Unprocessable Entity", str(exc)) from exc

    out = ImportOut(
        committed=False,
        total=parsed.total,
        valid=len(parsed.rows),
        errors=[{"row": e.row, "message": e.message} for e in parsed.errors],
        sample=[_jsonable(r) for r in parsed.rows[:PREVIEW_ROWS]],
    )
    if not body.commit:
        return out
    if parsed.errors or not parsed.rows:
        raise ProblemException(
            422, "Unprocessable Entity",
            "Fix the rows with errors before importing; nothing was saved.",
        )

    model, key = (SocialPost, "ref") if body.kind == "posts" else (SocialDaily, "day")
    values = [{**r, "tenant_id": current.tenant_id, "account_id": account.id} for r in parsed.rows]
    stmt = insert(model)
    fields = (
        (*POST_COUNTS, "title", "format", "posted_at")
        if body.kind == "posts"
        else ("followers", "reach", "impressions")
    )
    update = {c: stmt.excluded[c] for c in fields}
    await db.execute(
        stmt.on_conflict_do_update(index_elements=["account_id", key], set_=update), values
    )
    log_audit(
        db, tenant_id=current.tenant_id, actor_id=current.user.id,
        action="social_account.imported", entity="social_account", entity_id=account.id,
        meta={"kind": body.kind, "rows": len(parsed.rows)}, ip=client_ip(request),
    )
    await db.commit()
    out.committed = True
    return out


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in row.items()}


@router.get("/social-accounts/{account_id}/metrics")
async def account_metrics(
    account_id: UUID, current: Annotated[CurrentUser, Depends(get_current_user)], db: DB
) -> dict[str, Any]:
    account = await _account_or_404(db, current, account_id)
    cols = (*POST_COUNTS, "ref", "posted_at", "title", "format")
    posts = [
        {c: getattr(p, c) for c in cols}
        for p in await db.scalars(
            select(SocialPost).where(
                SocialPost.account_id == account.id, SocialPost.tenant_id == current.tenant_id
            )
        )
    ]
    daily = [
        {c: getattr(d, c) for c in ("day", "followers", "reach", "impressions")}
        for d in await db.scalars(
            select(SocialDaily).where(
                SocialDaily.account_id == account.id, SocialDaily.tenant_id == current.tenant_id
            )
        )
    ]
    return {"platform": account.platform, "handle": account.handle, **compute_metrics(posts, daily)}
