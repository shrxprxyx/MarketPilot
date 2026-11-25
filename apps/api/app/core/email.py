"""Email addresses are case-insensitive in practice, so they are stored and compared in
lower case: `Ann@x.com` and `ann@x.com` are one account, one lockout counter, one invite."""
from typing import Annotated

from pydantic import AfterValidator, EmailStr

NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
