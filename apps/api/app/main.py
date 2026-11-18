import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health, ready
from app.config import settings
from app.core.errors import unhandled_exception_handler
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

app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]

app.include_router(health.router, prefix="/api/v1")
app.include_router(ready.router, prefix="/api/v1")