"""
Recordings Domain — Pydantic Schemas (Request/Response)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator

from autoflow.recordings.models import (
    RecordingSource,
    RecordingStatus,
    SemanticActionType,
)

# ─── Element Identification ───────────────────────────────────────────────────

class ElementInfo(BaseModel):
    """Semantic element descriptor — no coordinates."""
    tag: str | None = None
    role: str | None = None
    aria_label: str | None = None
    text: str | None = None
    placeholder: str | None = None
    element_id: str | None = None
    parent_context: str | None = None  # Surrounding semantic context


# ─── Raw Events ───────────────────────────────────────────────────────────────

class RawEventCreate(BaseModel):
    """Incoming event from the Chrome Extension."""
    event_type: str = Field(..., max_length=50)
    sequence_number: int = Field(..., ge=0)
    client_timestamp: int = Field(..., description="Unix timestamp in milliseconds")
    url: str | None = None
    page_title: str | None = Field(None, max_length=500)
    element: ElementInfo | None = None
    value: str | None = Field(None, max_length=10000)  # Sanitize large inputs
    payload: dict[str, Any] | None = None

    @field_validator("value", mode="before")
    @classmethod
    def truncate_value(cls, v: str | None) -> str | None:
        """Truncate very long values (passwords, large pastes)."""
        if v and len(v) > 10000:
            return v[:10000] + "...[truncated]"
        return v


class RawEventBatchCreate(BaseModel):
    """Batch of events sent from the extension (more efficient than one-by-one)."""
    events: list[RawEventCreate] = Field(..., min_length=1, max_length=1000)


class RawEventResponse(BaseModel):
    """Response representation of a raw event."""
    id: uuid.UUID
    session_id: uuid.UUID
    event_type: str
    sequence_number: int
    client_timestamp: int
    url: str | None
    page_title: str | None
    element_tag: str | None
    element_role: str | None
    element_aria_label: str | None
    element_text: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Semantic Actions ─────────────────────────────────────────────────────────

class SemanticActionResponse(BaseModel):
    """A high-level semantic action derived from raw events."""
    id: uuid.UUID
    session_id: uuid.UUID
    action_type: SemanticActionType
    description: str
    sequence_number: int
    url: str | None
    application: str | None
    extracted_data: dict[str, Any] | None
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Recording Sessions ───────────────────────────────────────────────────────

class RecordingSessionCreate(BaseModel):
    """Start a new recording session."""
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    source: RecordingSource = RecordingSource.BROWSER_EXTENSION
    metadata: dict[str, Any] | None = None


class RecordingSessionUpdate(BaseModel):
    """Update recording session metadata."""
    name: str | None = Field(None, max_length=255)
    description: str | None = None


class RecordingSessionResponse(BaseModel):
    """Full recording session with all details."""
    id: uuid.UUID
    name: str | None
    description: str | None
    source: RecordingSource
    status: RecordingStatus
    raw_event_count: int
    semantic_action_count: int
    duration_seconds: int | None
    error_message: str | None
    # ORM attribute is session_metadata ("metadata" is reserved by SQLAlchemy); the API field stays "metadata"
    metadata: dict[str, Any] | None = Field(
        None, validation_alias=AliasChoices("session_metadata", "metadata")
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecordingSessionWithActions(RecordingSessionResponse):
    """Recording session with full semantic action list."""
    semantic_actions: list[SemanticActionResponse] = []


class RecordingSessionListResponse(BaseModel):
    """Paginated list of recording sessions."""
    items: list[RecordingSessionResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


# ─── WebSocket Messages ───────────────────────────────────────────────────────

class WSEventMessage(BaseModel):
    """Message format for WebSocket real-time streaming."""
    type: str  # "event_ingested" | "action_created" | "processing_complete" | "error"
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class IngestResponse(BaseModel):
    """Response after ingesting a batch of events."""
    session_id: uuid.UUID
    events_ingested: int
    total_events: int


class HSAEExtractionResponse(BaseModel):
    """Output of the HSAE pipeline for one recording."""
    recording_id: str
    raw_event_count: int
    filtered_event_count: int
    actions: list[dict[str, Any]]
    intent: dict[str, Any]
    workflow: dict[str, Any] | None
    processing_time_ms: float
    layer_times_ms: dict[str, float]
    errors: list[str]
