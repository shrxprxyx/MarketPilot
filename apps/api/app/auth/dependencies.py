import logging
import uuid
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import decode_access_token
from app.core.errors import problem

logger = logging.getLogger(__name__)
_bearer = HTTPBearer()


class CurrentUser:
    def __init__(self, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.role = role


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> CurrentUser:
    try:
        payload = decode_access_token(creds.credentials)
        return CurrentUser(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tenant"]),
            role=payload["role"],
        )
    except jwt.ExpiredSignatureError as err:
        raise problem(401, "Unauthorized", "Token has expired.") from err  # type: ignore[misc]
    except jwt.PyJWTError as err:
        raise problem(401, "Unauthorized", "Invalid token.") from err  # type: ignore[misc]


Auth = Annotated[CurrentUser, Depends(get_current_user)]