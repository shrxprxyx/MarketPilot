from uuid import UUID


def enqueue_ingest(tenant_id: UUID, document_id: UUID, job_id: UUID | None = None) -> None:
    """Hands ingestion to the Celery worker. Kept behind a function so tests can
    replace it without a broker. `job_id` links the run to its row in `jobs`."""
    from app.jobs.rag_tasks import ingest_task

    ingest_task.delay(str(tenant_id), str(document_id), str(job_id) if job_id else None)
