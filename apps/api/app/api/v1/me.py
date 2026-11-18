from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/me", tags=["me"])


class MeOut(BaseModel):
    user_id: UUID
    tenant_id: UUID
    role: str


@router.get("", response_model=MeOut)
async def get_me(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> MeOut:
    return MeOut(
        user_id=current.user.id,
        tenant_id=current.tenant_id,
        role=current.role,
    )
