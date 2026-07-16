from django.conf import settings


def should_run_eager() -> bool:
    """
    Run bulk work inline (in-process, synchronously) when either:
      • Celery is in eager mode (CELERY_TASK_ALWAYS_EAGER), or
      • no broker is configured.

    This keeps SQLite / broker-less dev fully functional while production
    (eager off, broker set) dispatches to a worker.
    """
    if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        return True
    return not (getattr(settings, 'CELERY_BROKER_URL', '') or '')


def run_or_dispatch(task, job, *task_args, **task_kwargs):
    """
    Execute a Celery `task` for the given `BulkJob`.

    Sync path (no broker / eager): run the task locally now and return the
    refreshed job, so callers can read its final status immediately.
    Async path: dispatch to the worker and return the job in its current
    (queued) state for the client to poll.

    The task's first positional argument is always the job id.
    """
    if should_run_eager():
        task.apply(args=(job.id, *task_args), kwargs=task_kwargs)
        job.refresh_from_db()
        return job
    task.delay(job.id, *task_args, **task_kwargs)
    return job
