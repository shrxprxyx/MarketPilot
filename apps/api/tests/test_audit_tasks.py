"""The Celery entry point of an audit and the enqueue hand-off, without a broker."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import app.audit.queue as queue
import app.jobs.audit_tasks as tasks


def test_the_task_runs_the_audit_with_the_given_ids() -> None:
    t, a, j = uuid4(), uuid4(), uuid4()
    with patch.object(tasks, "run_audit", new=AsyncMock()) as run:
        tasks.website_audit_task(str(t), str(a), str(j))
    args = run.await_args.args
    assert args[1:] == (t, a, j)


def test_enqueue_sends_string_ids_to_celery() -> None:
    t, a, j = uuid4(), uuid4(), uuid4()
    with patch.object(tasks.website_audit_task, "delay", new=MagicMock()) as delay:
        queue.enqueue_website_audit(t, a, j)
    delay.assert_called_once_with(str(t), str(a), str(j))
