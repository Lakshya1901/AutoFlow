"""
Execution Engine — Celery Tasks
Background tasks for workflow execution.
"""

from __future__ import annotations

import asyncio
import uuid

from autoflow.core.logging import get_logger
from autoflow.execution.celery_app import celery_app

logger = get_logger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="autoflow.execution.tasks.execute_workflow_task",
    queue="execution",
    max_retries=0,  # Engine handles its own retries per-step
    acks_late=True,
    track_started=True,
)
def execute_workflow_task(
    self,
    workflow_id: str,
    run_id: str,
) -> dict:
    """
    Celery task to execute a workflow run.

    Called by the API when a user triggers a workflow.
    Runs the full workflow engine in an async context.
    """
    logger.info(
        "Workflow execution task started",
        workflow_id=workflow_id,
        run_id=run_id,
        celery_task_id=self.request.id,
    )

    async def _execute():
        from autoflow.core.database import AsyncSessionFactory
        from autoflow.workflows.service import WorkflowService

        async with AsyncSessionFactory() as db:
            service = WorkflowService(db)
            try:
                run = await service.execute_run(
                    uuid.UUID(workflow_id),
                    uuid.UUID(run_id),
                )
                await db.commit()
                return {
                    "success": True,
                    "run_id": str(run.id),
                    "status": run.status.value,
                }
            except Exception as e:
                await db.rollback()
                logger.exception(
                    "Workflow execution failed",
                    workflow_id=workflow_id,
                    run_id=run_id,
                    error=str(e),
                )
                return {
                    "success": False,
                    "run_id": run_id,
                    "error": str(e),
                }

    return _run_async(_execute())


@celery_app.task(
    bind=True,
    name="autoflow.execution.tasks.resume_workflow_run",
    queue="execution",
    max_retries=0,
    acks_late=True,
)
def resume_workflow_run(self, workflow_id: str, run_id: str) -> dict:  # noqa: ARG001 - bound Celery task
    """
    Resume a workflow run that was waiting for approval.

    Called after an approval checkpoint is approved via the API.
    """
    logger.info(
        "Resuming workflow run after approval",
        workflow_id=workflow_id,
        run_id=run_id,
    )

    async def _resume():
        from autoflow.core.database import AsyncSessionFactory
        from autoflow.workflows.service import WorkflowService

        async with AsyncSessionFactory() as db:
            service = WorkflowService(db)
            try:
                run = await service.execute_run(
                    uuid.UUID(workflow_id),
                    uuid.UUID(run_id),
                )
                await db.commit()
                return {"success": True, "run_id": str(run.id)}
            except Exception as e:
                await db.rollback()
                return {"success": False, "error": str(e)}

    return _run_async(_resume())


@celery_app.task(
    name="autoflow.execution.tasks.cleanup_old_runs",
    queue="default",
)
def cleanup_old_runs(days: int = 30) -> dict:
    """
    Periodic task to archive old workflow run records.
    Scheduled via Celery Beat to run daily.
    """
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=days)

    async def _cleanup():
        from sqlalchemy import delete

        from autoflow.core.database import AsyncSessionFactory
        from autoflow.workflows.models import WorkflowRun, WorkflowRunStatus

        async with AsyncSessionFactory() as db:
            result = await db.execute(
                delete(WorkflowRun)
                .where(WorkflowRun.created_at < cutoff)
                .where(
                    WorkflowRun.status.in_([
                        WorkflowRunStatus.COMPLETED,
                        WorkflowRunStatus.FAILED,
                        WorkflowRunStatus.CANCELLED,
                    ])
                )
            )
            await db.commit()
            return {"deleted_runs": result.rowcount}

    return _run_async(_cleanup())
