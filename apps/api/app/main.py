import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    ai_connections,
    ai_routes,
    ai_usage,
    audit,
    auth,
    clients,
    health,
    me,
    members,
    ready,
)
from app.config import settings
from app.core.errors import ProblemException, problem_exception_handler, unhandled_exception_handler
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s", settings.app_name)
    yield
    logger.info("Stopping %s", settings.app_name)


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(ProblemException, problem_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router, prefix="/api/v1")
app.include_router(ready.router, prefix="/api/v1")
app.include_router(me.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(clients.router, prefix="/api/v1")
app.include_router(members.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(ai_connections.router, prefix="/api/v1")
app.include_router(ai_routes.router, prefix="/api/v1")
app.include_router(ai_usage.router, prefix="/api/v1")
