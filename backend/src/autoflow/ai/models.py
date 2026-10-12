"""
AI Planner — SQLAlchemy Models
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from autoflow.core.database import Base, JSONType


class IntentAnalysis(Base):
    """Stores AI-extracted intent from a recording session."""

    __tablename__ = "intent_analyses"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("recording_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # AI-extracted intent
    intent: Mapped[str] = mapped_column(String(500), nullable=False)
    goal_summary: Mapped[str] = mapped_column(Text, nullable=False)
    steps_summary: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    detected_variables: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)
    suggested_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI metadata
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ai_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # Full raw response for debugging
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)


class WorkflowSuggestion(Base):
    """
    AI-generated workflow definition derived from intent analysis.
    The user reviews and edits this before it becomes a real Workflow.
    """

    __tablename__ = "workflow_suggestions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("recording_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intent_analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("intent_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Generated workflow definition (full JSON tree)
    workflow_definition: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)

    # Whether the user accepted and converted this to a real workflow
    accepted: Mapped[bool] = mapped_column(default=False)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
    )

    # AI metadata
    ai_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_model: Mapped[str] = mapped_column(String(100), nullable=False)
