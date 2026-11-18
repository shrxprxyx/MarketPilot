from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_access_token
from app.core.errors import ProblemException
from app.db.rls import set_rls_context
from app.db.session import get_db
from app.models.membership import Membership
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, user: User, tenant_id: UUID, role: str) -> None:
        self.user = user
        self.tenant_id = tenant_id
        self.role = role


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    if not credentials:
        raise ProblemException(401, "Unauthorized", "Missing bearer token.")

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise ProblemException(401, "Unauthorized", "Invalid or expired access token.")

    user_id = UUID(payload["sub"])
    tenant_id = UUID(payload["tenant_id"])
    role = payload.get("role", "member")

    # Set RLS context before any tenant-scoped query runs on this session.
    await set_rls_context(db, tenant_id=tenant_id, user_id=user_id)

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise ProblemException(401, "Unauthorized", "User not found.")

    # Verify membership still exists (not removed since token was issued)
    membership = await db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
        )
    )
    if not membership:
        raise ProblemException(403, "Forbidden", "Not a member of this tenant.")

    return CurrentUser(user=user, tenant_id=tenant_id, role=role)


def require_role(*roles: str) -> Any:
    """Dependency factory: require the current user to have one of the given roles."""
    async def _check(
        current: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if current.role not in roles:
            raise ProblemException(
                403, "Forbidden",
                f"Requires role: {' or '.join(roles)}. You have: {current.role}."
            )
        return current
    return Depends(_check)
