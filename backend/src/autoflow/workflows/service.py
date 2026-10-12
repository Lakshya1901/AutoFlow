"""
Workflows Domain — Business Logic Service
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from autoflow.core.events import WorkflowCreated, WorkflowUpdated, event_bus
from autoflow.core.logging import get_logger
from autoflow.workflows.models import (
    StepType,
    TriggerType,
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowStep,
    WorkflowVariable,
)
from autoflow.workflows.schemas import (
    WorkflowCreate,
    WorkflowRunCreate,
    WorkflowUpdate,
)

logger = get_logger(__name__)


class WorkflowService:
    """Business logic for workflow management and execution."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_workflow(self, data: WorkflowCreate) -> Workflow:
        """Create a new workflow with steps and variables."""
        workflow = Workflow(
            name=data.name,
            description=data.description,
            trigger_type=data.trigger_type,
            trigger_config=data.trigger_config,
            tags=data.tags,
            definition=data.definition,
            source_recording_id=data.source_recording_id,
            status=WorkflowStatus.DRAFT,
        )
        self._db.add(workflow)
        await self._db.flush()  # Get workflow ID

        # Create steps
        for step_data in data.steps:
            step = WorkflowStep(
                workflow_id=workflow.id,
                **step_data.model_dump(),
            )
            self._db.add(step)

        # Create variables
        for var_data in data.variables:
            variable = WorkflowVariable(
                workflow_id=workflow.id,
                **var_data.model_dump(),
            )
            self._db.add(variable)

        await self._db.flush()

        await event_bus.publish(WorkflowCreated(workflow_id=workflow.id, name=workflow.name))
        logger.info("Workflow created", workflow_id=str(workflow.id), name=workflow.name)
        return workflow

    async def create_from_suggestion(
        self, suggestion_id: uuid.UUID, name_override: str | None = None
    ) -> Workflow:
        """Convert an AI workflow suggestion into a real workflow."""
        from sqlalchemy import select as sql_select

        from autoflow.ai.models import WorkflowSuggestion

        result = await self._db.execute(
            sql_select(WorkflowSuggestion).where(WorkflowSuggestion.id == suggestion_id)
        )
        suggestion = result.scalar_one_or_none()
        if not suggestion:
            raise ValueError(f"Workflow suggestion {suggestion_id} not found")

        definition = suggestion.workflow_definition
        name = name_override or definition.get("name", "Untitled Workflow")

        # Build WorkflowCreate from the AI definition
        steps = []
        for i, step_def in enumerate(definition.get("steps", [])):
            steps.append({
                "step_key": step_def.get("id", f"step_{i:03d}"),
                "name": step_def.get("name", f"Step {i + 1}"),
                "description": step_def.get("description"),
                "step_type": self._map_step_type(step_def.get("type", "connector_action")),
                "connector": step_def.get("connector"),
                "config": step_def.get("config", {}),
                "position": i,
                "on_error": step_def.get("on_error", "stop"),
                "max_retries": step_def.get("max_retries", 0),
                "requires_approval": step_def.get("requires_approval", False),
                "outputs": step_def.get("outputs"),
            })

        variables = []
        for var_def in definition.get("variables", []):
            variables.append({
                "name": var_def.get("name", "variable"),
                "description": var_def.get("description"),
                "default_value": var_def.get("default"),
                "is_required": var_def.get("required", True),
            })

        create_data = WorkflowCreate(
            name=name,
            description=definition.get("description"),
            trigger_type=self._map_trigger_type(definition.get("trigger", {}).get("type", "manual")),
            trigger_config=definition.get("trigger", {}).get("config"),
            definition=definition,
            source_recording_id=suggestion.session_id,
            steps=[],  # Created separately for simplicity
            variables=[],
        )

        workflow = await self.create_workflow(create_data)

        # Mark suggestion as accepted
        await self._db.execute(
            update(WorkflowSuggestion if True else None)
            .where(WorkflowSuggestion.id == suggestion_id)
            .values(accepted=True, workflow_id=workflow.id)
        )

        return workflow

    def _map_step_type(self, type_str: str) -> StepType:
        """Map AI-generated step type strings to StepType enum."""
        mapping = {
            "browser_navigate": StepType.BROWSER_NAVIGATE,
            "browser_click": StepType.BROWSER_CLICK,
            "browser_input": StepType.BROWSER_INPUT,
            "browser_extract": StepType.BROWSER_EXTRACT,
            "browser_download": StepType.BROWSER_DOWNLOAD,
            "file_rename": StepType.FILE_RENAME,
            "file_move": StepType.FILE_MOVE,
            "file_create_folder": StepType.FILE_CREATE_FOLDER,
            "approval_checkpoint": StepType.APPROVAL_CHECKPOINT,
            "notification": StepType.NOTIFICATION,
            "http_request": StepType.HTTP_REQUEST,
            "condition": StepType.CONDITION,
        }
        return mapping.get(type_str.lower(), StepType.CONNECTOR_ACTION)

    def _map_trigger_type(self, type_str: str) -> TriggerType:
        mapping = {
            "manual": TriggerType.MANUAL,
            "schedule": TriggerType.SCHEDULE,
            "webhook": TriggerType.WEBHOOK,
            "event": TriggerType.EVENT,
        }
        return mapping.get(type_str.lower(), TriggerType.MANUAL)

    async def get_workflow(self, workflow_id: uuid.UUID) -> Workflow | None:
        """Get a workflow with all steps and variables."""
        result = await self._db.execute(
            select(Workflow)
            .where(Workflow.id == workflow_id)
            .options(
                selectinload(Workflow.steps),
                selectinload(Workflow.variables),
            )
        )
        return result.scalar_one_or_none()

    async def list_workflows(
        self,
        page: int = 1,
        page_size: int = 20,
        status: WorkflowStatus | None = None,
    ) -> tuple[list[Workflow], int]:
        """List workflows with optional status filter and pagination."""
        query = select(Workflow).order_by(Workflow.updated_at.desc())
        count_query = select(func.count()).select_from(Workflow)

        if status:
            query = query.where(Workflow.status == status)
            count_query = count_query.where(Workflow.status == status)

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        total_result = await self._db.execute(count_query)
        total = total_result.scalar_one()

        result = await self._db.execute(query)
        return list(result.scalars().all()), total

    async def update_workflow(self, workflow_id: uuid.UUID, data: WorkflowUpdate) -> Workflow:
        """Update workflow metadata."""
        workflow = await self._get_or_raise(workflow_id)
        update_data = data.model_dump(exclude_none=True)
        for key, value in update_data.items():
            setattr(workflow, key, value)

        await event_bus.publish(WorkflowUpdated(workflow_id=workflow_id))
        return workflow

    async def update_workflow_definition(
        self, workflow_id: uuid.UUID, definition: dict[str, Any]
    ) -> Workflow:
        """Update the full workflow definition (from editor or NL edit)."""
        await self._db.execute(
            update(Workflow)
            .where(Workflow.id == workflow_id)
            .values(definition=definition, version=Workflow.version + 1)
        )
        await self._db.flush()
        return await self._get_or_raise(workflow_id)

    async def delete_workflow(self, workflow_id: uuid.UUID) -> None:
        """Delete a workflow and all its runs."""
        workflow = await self._get_or_raise(workflow_id)
        await self._db.delete(workflow)

    async def clone_workflow(self, workflow_id: uuid.UUID, new_name: str | None = None) -> Workflow:
        """Clone a workflow."""
        original = await self.get_workflow(workflow_id)
        if not original:
            raise ValueError(f"Workflow {workflow_id} not found")

        create_data = WorkflowCreate(
            name=new_name or f"{original.name} (Copy)",
            description=original.description,
            trigger_type=original.trigger_type,
            trigger_config=original.trigger_config,
            tags=original.tags,
            definition=original.definition,
        )
        return await self.create_workflow(create_data)

    # ─── Execution ────────────────────────────────────────────────────────────

    async def create_run(
        self, workflow_id: uuid.UUID, data: WorkflowRunCreate
    ) -> WorkflowRun:
        """Create a new run record and queue it for execution."""
        await self._get_or_raise(workflow_id)  # 404 if the workflow is gone

        run = WorkflowRun(
            workflow_id=workflow_id,
            status=WorkflowRunStatus.QUEUED,
            variable_values=data.variable_values,
            triggered_by=data.triggered_by,
            completed_steps=[],
        )
        self._db.add(run)
        await self._db.flush()

        logger.info(
            "Workflow run created",
            workflow_id=str(workflow_id),
            run_id=str(run.id),
            triggered_by=data.triggered_by,
        )

        return run

    async def execute_run(self, workflow_id: uuid.UUID, run_id: uuid.UUID) -> WorkflowRun:
        """Execute a workflow run (called by Celery worker)."""
        from autoflow.workflows.engine import WorkflowEngine

        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        result = await self._db.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise ValueError(f"Run {run_id} not found")

        engine = WorkflowEngine(self._db)
        return await engine.execute(workflow, run, run.variable_values)

    async def approve_run(self, run_id: uuid.UUID) -> WorkflowRun:
        """Resume a run that's waiting for approval."""
        result = await self._db.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise ValueError(f"Run {run_id} not found")

        if run.status != WorkflowRunStatus.WAITING_FOR_APPROVAL:
            raise ValueError(f"Run {run_id} is not waiting for approval")

        # Resume execution via Celery
        from autoflow.execution.tasks import resume_workflow_run
        resume_workflow_run.delay(str(run.workflow_id), str(run_id))

        return run

    async def get_run(self, run_id: uuid.UUID) -> WorkflowRun | None:
        """Get a run by ID."""
        result = await self._db.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_runs(
        self, workflow_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[WorkflowRun], int]:
        """List runs for a workflow."""
        offset = (page - 1) * page_size

        count_result = await self._db.execute(
            select(func.count()).select_from(WorkflowRun).where(
                WorkflowRun.workflow_id == workflow_id
            )
        )
        total = count_result.scalar_one()

        result = await self._db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.workflow_id == workflow_id)
            .order_by(WorkflowRun.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def cancel_run(self, run_id: uuid.UUID) -> WorkflowRun:
        """Cancel a queued or running workflow run."""
        result = await self._db.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise ValueError(f"Run {run_id} not found")

        if run.status in (WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED):
            raise ValueError(f"Run {run_id} is already {run.status}")

        await self._db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(status=WorkflowRunStatus.CANCELLED)
        )

        # Revoke Celery task if running
        if run.celery_task_id:
            from autoflow.execution.celery_app import celery_app
            celery_app.control.revoke(run.celery_task_id, terminate=True)

        return run

    async def _get_or_raise(self, workflow_id: uuid.UUID) -> Workflow:
        """Get a workflow or raise ValueError."""
        result = await self._db.execute(
            select(Workflow).where(Workflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")
        return workflow
