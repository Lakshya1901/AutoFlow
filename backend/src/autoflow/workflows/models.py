"""
Workflows Domain — SQLAlchemy Models
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoflow.core.database import Base, JSONType


class WorkflowStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class WorkflowRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class StepType(str, enum.Enum):
    # Browser actions
    BROWSER_NAVIGATE = "browser_navigate"
    BROWSER_CLICK = "browser_click"
    BROWSER_INPUT = "browser_input"
    BROWSER_EXTRACT = "browser_extract"
    BROWSER_DOWNLOAD = "browser_download"
    BROWSER_UPLOAD = "browser_upload"
    BROWSER_WAIT = "browser_wait"

    # File system
    FILE_RENAME = "file_rename"
    FILE_MOVE = "file_move"
    FILE_COPY = "file_copy"
    FILE_CREATE_FOLDER = "file_create_folder"
    FILE_DELETE = "file_delete"

    # Data
    DATA_TRANSFORM = "data_transform"
    DATA_EXTRACT = "data_extract"

    # Control flow
    CONDITION = "condition"
    LOOP = "loop"
    APPROVAL_CHECKPOINT = "approval_checkpoint"
    WAIT = "wait"

    # Notifications
    NOTIFICATION = "notification"
    WEBHOOK = "webhook"
    HTTP_REQUEST = "http_request"

    # Connectors (extensible)
    CONNECTOR_ACTION = "connector_action"


class TriggerType(str, enum.Enum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"
    EVENT = "event"


class VariableType(str, enum.Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    EMAIL = "email"
    FILE_PATH = "file_path"
    URL = "url"
    JSON = "json"


class Workflow(Base):
    """
    A reusable, executable workflow.

    A workflow is the core product entity of AutoFlow.
    It contains steps, variables, trigger configuration,
    and a full execution history.
    """

    __tablename__ = "workflows"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus), default=WorkflowStatus.DRAFT, nullable=False
    )

    # Version tracking
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Source tracking
    source_recording_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("recording_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Trigger configuration
    trigger_type: Mapped[TriggerType] = mapped_column(
        Enum(TriggerType), default=TriggerType.MANUAL, nullable=False
    )
    trigger_config: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # For SCHEDULE: {"cron": "0 9 * * 1-5", "timezone": "America/New_York"}
    # For WEBHOOK: {"secret": "...", "method": "POST"}

    # Full workflow definition snapshot (for versioning/export)
    definition: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # Statistics
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    successful_runs: Mapped[int] = mapped_column(Integer, default=0)
    failed_runs: Mapped[int] = mapped_column(Integer, default=0)
    avg_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    estimated_time_saved_minutes: Mapped[float] = mapped_column(Float, default=0.0)

    # Tags for organization
    tags: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    # Relationships
    steps: Mapped[list[WorkflowStep]] = relationship(
        "WorkflowStep", back_populates="workflow", cascade="all, delete-orphan",
        order_by="WorkflowStep.position"
    )
    variables: Mapped[list[WorkflowVariable]] = relationship(
        "WorkflowVariable", back_populates="workflow", cascade="all, delete-orphan"
    )
    runs: Mapped[list[WorkflowRun]] = relationship(
        "WorkflowRun", back_populates="workflow", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_workflows_status", "status"),
        Index("ix_workflows_created_at", "created_at"),
    )


class WorkflowStep(Base):
    """
    A single step in a workflow.

    Steps are the atomic units of execution. Each step has a type,
    configuration, and can reference workflow variables.
    """

    __tablename__ = "workflow_steps"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )

    # Identification
    step_key: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "step_001"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Type and execution
    step_type: Mapped[StepType] = mapped_column(Enum(StepType), nullable=False)
    connector: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g., "browser", "gmail"
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # Type-specific config. Example for browser_navigate:
    # {"url": "https://mail.google.com", "wait_for": "load"}

    # Positioning in the visual editor
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    position_x: Mapped[float | None] = mapped_column(Float, nullable=True)  # Canvas X coordinate
    position_y: Mapped[float | None] = mapped_column(Float, nullable=True)  # Canvas Y coordinate

    # Control flow
    next_step_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    on_success_step_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    on_failure_step_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)  # Python expression

    # Error handling
    on_error: Mapped[str] = mapped_column(String(20), default="stop")  # stop | continue | retry
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=5)

    # Approval requirements
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)

    # Outputs (what this step produces — variable mappings)
    outputs: Mapped[dict[str, str] | None] = mapped_column(JSONType, nullable=True)
    # e.g., {"downloaded_file": "The path to the downloaded file"}

    # Metadata
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="steps")

    __table_args__ = (
        Index("ix_workflow_steps_workflow_id", "workflow_id"),
    )


class WorkflowVariable(Base):
    """
    A parameterized variable in a workflow.

    Variables make workflows reusable. Instead of hardcoding
    "Acme Corp", the workflow uses {{client_name}}.
    """

    __tablename__ = "workflow_variables"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "client_name"
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    variable_type: Mapped[VariableType] = mapped_column(
        Enum(VariableType), default=VariableType.STRING, nullable=False
    )
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)  # Encrypt at rest

    # Relationship
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="variables")

    __table_args__ = (
        Index("ix_workflow_variables_workflow_id", "workflow_id"),
    )


class WorkflowRun(Base):
    """
    A single execution instance of a workflow.

    Provides full audit trail with:
    - Execution status and timing
    - Variable values used in this run
    - Step execution logs
    - Error details
    """

    __tablename__ = "workflow_runs"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[WorkflowRunStatus] = mapped_column(
        Enum(WorkflowRunStatus), default=WorkflowRunStatus.QUEUED, nullable=False
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Variable values for this run (snapshot)
    variable_values: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # Execution progress
    current_step_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    completed_steps: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    # Results
    outputs: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # Error information
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_step_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Trigger information
    triggered_by: Mapped[str] = mapped_column(String(50), default="manual")
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Step-level execution logs
    step_logs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)

    # Relationship
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="runs")

    __table_args__ = (
        Index("ix_workflow_runs_workflow_id", "workflow_id"),
        Index("ix_workflow_runs_status", "status"),
    )


class WorkflowEvent(Base):
    """
    Immutable event log for event sourcing.

    Every state change in a workflow or run is recorded here.
    Used for audit trails, debugging, and time-travel inspection.
    """

    __tablename__ = "workflow_events"

    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=True
    )

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    __table_args__ = (
        Index("ix_workflow_events_workflow_id", "workflow_id"),
        Index("ix_workflow_events_run_id", "run_id"),
        Index("ix_workflow_events_event_type", "event_type"),
    )
