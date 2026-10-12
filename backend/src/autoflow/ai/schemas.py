"""
AI Planner — Pydantic Schemas
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ─── Intent Extraction ────────────────────────────────────────────────────────

class DetectedVariable(BaseModel):
    name: str
    description: str
    example: str | None = None
    type: str = "string"  # string, number, date, email, file


class IntentExtractionRequest(BaseModel):
    """Request to extract intent from a recording session."""
    session_id: uuid.UUID


class IntentExtractionResponse(BaseModel):
    """AI-extracted intent from a recording session."""
    id: uuid.UUID
    session_id: uuid.UUID
    intent: str
    goal_summary: str
    steps_summary: list[str] | None
    detected_variables: list[dict[str, Any]] | None
    suggested_name: str | None
    notes: str | None
    confidence: float
    ai_provider: str
    ai_model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Workflow Suggestion ──────────────────────────────────────────────────────

class WorkflowGenerationRequest(BaseModel):
    """Generate a workflow from an intent analysis."""
    intent_analysis_id: uuid.UUID


class WorkflowSuggestionResponse(BaseModel):
    """AI-generated workflow suggestion."""
    id: uuid.UUID
    session_id: uuid.UUID
    intent_analysis_id: uuid.UUID
    workflow_definition: dict[str, Any]
    accepted: bool
    workflow_id: uuid.UUID | None
    ai_provider: str
    ai_model: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AcceptWorkflowSuggestionRequest(BaseModel):
    """Accept a workflow suggestion and create a real workflow."""
    suggestion_id: uuid.UUID
    name: str | None = None  # Override the suggested name


# ─── Natural Language Editing ─────────────────────────────────────────────────

class NaturalLanguageEditRequest(BaseModel):
    """Edit a workflow using natural language."""
    workflow_id: uuid.UUID
    instruction: str = Field(..., min_length=5, max_length=1000)


class NaturalLanguageEditResponse(BaseModel):
    """Result of a natural language workflow edit."""
    workflow_id: uuid.UUID
    instruction: str
    changes_applied: list[str]  # Human-readable list of changes made
    updated_workflow: dict[str, Any] | None  # The updated workflow definition


# ─── Health Check ─────────────────────────────────────────────────────────────

class AIHealthResponse(BaseModel):
    """AI provider health check response."""
    status: str  # "healthy" | "unhealthy"
    provider: str
    model: str
    response: str | None = None
    error: str | None = None
