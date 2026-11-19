# app/db/base_imports.py
# This file exists solely to import all ORM models so that
# Base.metadata is populated before Alembic autogenerate runs.

from app.db.base import Base  # noqa: F401
from app.models.ai_connection import AIConnection  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.brand_profile import BrandProfile  # noqa: F401
from app.models.client import Client  # noqa: F401
from app.models.invite import Invite  # noqa: F401
from app.models.membership import Membership  # noqa: F401
from app.models.model_pricing import ModelPricing  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.task_model_route import TaskModelRoute  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
from app.models.usage_log import UsageLog  # noqa: F401
from app.models.user import User  # noqa: F401
