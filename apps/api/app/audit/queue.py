from uuid import UUID


def enqueue_website_audit(tenant_id: UUID, audit_id: UUID, job_id: UUID) -> None:
    """Hands the audit to the Celery worker. Kept behind a function so tests can replace it
    without a broker."""
    from app.jobs.audit_tasks import website_audit_task

    website_audit_task.delay(str(tenant_id), str(audit_id), str(job_id))
