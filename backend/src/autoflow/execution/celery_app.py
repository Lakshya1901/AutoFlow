"""
Execution Engine — Celery Application
"""

from __future__ import annotations

from celery import Celery

from autoflow.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "autoflow",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "autoflow.execution.tasks",
    ],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task behavior
    task_track_started=True,
    task_acks_late=True,           # Acknowledge only after completion (at-least-once delivery)
    worker_prefetch_multiplier=1,  # One task at a time per worker (prevent memory issues)

    # Result storage
    result_expires=86400,          # Results expire after 24 hours

    # Queue routing
    task_routes={
        "autoflow.execution.tasks.execute_workflow_task": {"queue": "execution"},
        "autoflow.execution.tasks.resume_workflow_run": {"queue": "execution"},
        "autoflow.execution.tasks.browser_action_task": {"queue": "browser"},
    },

    # Retry defaults
    task_default_retry_delay=30,
    task_max_retries=3,

    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)
