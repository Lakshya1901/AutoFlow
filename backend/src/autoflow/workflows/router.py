"""
Workflows Domain — API Router
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from autoflow.core.database import get_db
from autoflow.workflows.models import WorkflowStatus
from autoflow.workflows.schemas import (
    WorkflowCreate,
    WorkflowDefinitionUpdate,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowRunCreate,
    WorkflowRunListResponse,
    WorkflowRunResponse,
    WorkflowUpdate,
    WorkflowWithSteps,
)
from autoflow.workflows.service import WorkflowService

router = APIRouter()


# ─── Workflow CRUD ────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=WorkflowWithSteps,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workflow",
)
async def create_workflow(
    data: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a new workflow from scratch or from a definition."""
    service = WorkflowService(db)
    workflow = await service.create_workflow(data)
    return await service.get_workflow(workflow.id)


@router.get(
    "",
    response_model=WorkflowListResponse,
    summary="List all workflows",
)
async def list_workflows(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    workflow_status: WorkflowStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List workflows with optional status filtering and pagination."""
    service = WorkflowService(db)
    workflows, total = await service.list_workflows(
        page=page, page_size=page_size, status=workflow_status
    )
    return WorkflowListResponse(
        items=workflows,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get(
    "/{workflow_id}",
    response_model=WorkflowWithSteps,
    summary="Get a workflow with its steps",
)
async def get_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a workflow by ID, including all steps and variables."""
    service = WorkflowService(db)
    workflow = await service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )
    return workflow


@router.put(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Update workflow metadata",
)
async def update_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Update workflow name, description, status, trigger, or tags."""
    service = WorkflowService(db)
    try:
        return await service.update_workflow(workflow_id, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put(
    "/{workflow_id}/definition",
    response_model=WorkflowWithSteps,
    summary="Update the full workflow definition",
)
async def update_workflow_definition(
    workflow_id: uuid.UUID,
    data: WorkflowDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Update the complete workflow definition from the visual editor.
    This increments the workflow version number.
    """
    service = WorkflowService(db)
    try:
        workflow = await service.update_workflow_definition(workflow_id, data.definition)
        return await service.get_workflow(workflow.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workflow",
)
async def delete_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a workflow and all its execution history."""
    service = WorkflowService(db)
    try:
        await service.delete_workflow(workflow_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/{workflow_id}/clone",
    response_model=WorkflowWithSteps,
    status_code=status.HTTP_201_CREATED,
    summary="Clone a workflow",
)
async def clone_workflow(
    workflow_id: uuid.UUID,
    new_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a copy of a workflow."""
    service = WorkflowService(db)
    try:
        cloned = await service.clone_workflow(workflow_id, new_name)
        return await service.get_workflow(cloned.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ─── Workflow Suggestions (from AI) ──────────────────────────────────────────

@router.post(
    "/from-suggestion/{suggestion_id}",
    response_model=WorkflowWithSteps,
    status_code=status.HTTP_201_CREATED,
    summary="Create workflow from AI suggestion",
)
async def create_from_suggestion(
    suggestion_id: uuid.UUID,
    name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Accept an AI-generated workflow suggestion and create a real workflow from it.
    The workflow will start in DRAFT status for the user to review.
    """
    service = WorkflowService(db)
    try:
        workflow = await service.create_from_suggestion(suggestion_id, name)
        return await service.get_workflow(workflow.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─── Workflow Execution ───────────────────────────────────────────────────────

@router.post(
    "/{workflow_id}/execute",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Execute a workflow",
)
async def execute_workflow(
    workflow_id: uuid.UUID,
    data: WorkflowRunCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Trigger a workflow execution.

    Returns 202 Accepted immediately with the run ID.
    Use the run ID to poll status or subscribe via WebSocket.

    Variable values provided here override the workflow's default values.
    """
    service = WorkflowService(db)

    # Verify workflow exists and is active
    workflow = await service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    if workflow.status == WorkflowStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot execute an archived workflow",
        )

    try:
        run = await service.create_run(workflow_id, data)

        # Queue execution via Celery
        from autoflow.execution.tasks import execute_workflow_task
        task = execute_workflow_task.delay(str(workflow_id), str(run.id))

        # Store task ID for potential cancellation
        from sqlalchemy import update

        from autoflow.workflows.models import WorkflowRun
        await db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run.id)
            .values(celery_task_id=task.id)
        )

        return run
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/runs/{run_id}/approve",
    response_model=WorkflowRunResponse,
    summary="Approve a workflow run checkpoint",
)
async def approve_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Approve a workflow run that's waiting at an approval checkpoint.
    The run will resume execution from where it paused.
    """
    service = WorkflowService(db)
    try:
        return await service.approve_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/runs/{run_id}/cancel",
    response_model=WorkflowRunResponse,
    summary="Cancel a workflow run",
)
async def cancel_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Cancel a queued or running workflow run."""
    service = WorkflowService(db)
    try:
        return await service.cancel_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{workflow_id}/runs",
    response_model=WorkflowRunListResponse,
    summary="List workflow runs",
)
async def list_runs(
    workflow_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all execution runs for a workflow, newest first."""
    service = WorkflowService(db)
    runs, total = await service.list_runs(workflow_id, page=page, page_size=page_size)
    return WorkflowRunListResponse(
        items=runs,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get(
    "/runs/{run_id}",
    response_model=WorkflowRunResponse,
    summary="Get a workflow run",
)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get the current status and logs of a workflow run."""
    service = WorkflowService(db)
    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    return run


# ─── Live Run Monitoring ──────────────────────────────────────────────────────

@router.websocket("/runs/{run_id}/live")
async def run_live_updates(run_id: uuid.UUID, websocket: WebSocket) -> None:
    """
    WebSocket endpoint for live workflow run monitoring.

    The frontend connects here to get real-time step-by-step execution updates.
    Updates are pushed as each step completes.
    """
    await websocket.accept()
    try:
        await websocket.send_json({
            "type": "connected",
            "data": {"run_id": str(run_id)},
        })
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
