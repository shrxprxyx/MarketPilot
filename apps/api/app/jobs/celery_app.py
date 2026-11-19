from celery import Celery

from app.config import settings

celery_app = Celery(
    "marketpilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.jobs.rag_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
)


@celery_app.task(name="jobs.ping")
def ping() -> str:
    return "pong"