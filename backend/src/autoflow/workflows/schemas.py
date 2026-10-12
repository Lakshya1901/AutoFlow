"""
Workflows Domain — Pydantic Schemas
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from autoflow.workflows.models import (
    StepType,
    TriggerType,
    VariableType,
    WorkflowRunStatus,
    WorkflowStatus,
)

# ─── Workflow Variables ───────────────────────────────────────────────────────

class WorkflowVariableCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str | None = None
    description: str | None = None
    variable_type: VariableType = VariableType.STRING
    default_value: str | None = None
    is_required: bool = True
    is_secret: bool = False


class WorkflowVariableResponse(WorkflowVariableCreate):
    id: uuid.UUID
    workflow_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Workflow Steps ───────────────────────────────────────────────────────────

class WorkflowStepCreate(BaseModel):
    step_key: str = Field(..., pattern=r"^step_\w+$")
    name: str
    description: str | None = None
    step_type: StepType
    connector: str | None = None
    config: dict[str, Any] | None = None
    position: int = Field(..., ge=0)
    position_x: float | None = None
    position_y: float | None = None
    next_step_key: str | None = None
    on_success_step_key: str | None = None
    on_failure_step_key: str | None = None
    condition: str | None = None
    on_error: str = "stop"
    max_retries: int = Field(default=0, ge=0, le=10)
    retry_delay_seconds: int = Field(default=5, ge=0)
    requires_approval: bool = False
    outputs: dict[str, str] | None = None
    is_disabled: bool = False
    notes: str | None = None


class WorkflowStepUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    position: int | None = None
    position_x: float | None = None
    position_y: float | None = None
    next_step_key: str | None = None
    condition: str | None = None
    on_error: str | None = None
    max_retries: int | None = None
    requires_approval: bool | None = None
    outputs: dict[str, str] | None = None
    is_disabled: bool | None = None
    notes: str | None = None


class WorkflowStepResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    step_key: str
    name: str
    description: str | None
    step_type: StepType
    connector: str | None
    config: dict[str, Any] | None
    position: int
    position_x: float | None
    position_y: float | None
    next_step_key: str | None
    on_success_step_key: str | None
    on_failure_step_key: str | None
    condition: str | None
    on_error: str
    max_retries: int
    requires_approval: bool
    outputs: dict[str, str] | None
    is_disabled: bool
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Workflows ────────────────────────────────────────────────────────────────

class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    trigger_type: TriggerType = TriggerType.MANUAL
    trigger_config: dict[str, Any] | None = None
    steps: list[WorkflowStepCreate] = []
    variables: list[WorkflowVariableCreate] = []
    tags: list[str] | None = None
    definition: dict[str, Any] | None = None
    source_recording_id: uuid.UUID | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: WorkflowStatus | None = None
    trigger_type: TriggerType | None = None
    trigger_config: dict[str, Any] | None = None
    tags: list[str] | None = None


class WorkflowDefinitionUpdate(BaseModel):
    """Full workflow definition update from the visual editor."""
    definition: dict[str, Any]
    steps: list[WorkflowStepCreate] | None = None
    variables: list[WorkflowVariableCreate] | None = None


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: WorkflowStatus
    version: int
    source_recording_id: uuid.UUID | None
    trigger_type: TriggerType
    trigger_config: dict[str, Any] | None
    definition: dict[str, Any] | None
    total_runs: int
    successful_runs: int
    failed_runs: int
    avg_duration_ms: int
    estimated_time_saved_minutes: float
    tags: list[str] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowWithSteps(WorkflowResponse):
    steps: list[WorkflowStepResponse] = []
    variables: list[WorkflowVariableResponse] = []


class WorkflowListResponse(BaseModel):
    items: list[WorkflowResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


# ─── Workflow Runs ────────────────────────────────────────────────────────────

class WorkflowRunCreate(BaseModel):
    """Trigger a workflow execution."""
    variable_values: dict[str, Any] | None = None
    triggered_by: str = "manual"


class WorkflowRunResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    status: WorkflowRunStatus
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    variable_values: dict[str, Any] | None
    current_step_key: str | None
    completed_steps: list[str] | None
    outputs: dict[str, Any] | None
    error_message: str | None
    error_step_key: str | None
    triggered_by: str
    step_logs: list[dict[str, Any]] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunListResponse(BaseModel):
    items: list[WorkflowRunResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
