"""
Recordings Domain — SQLAlchemy Models
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from autoflow.core.database import Base, JSONType


class RecordingStatus(str, enum.Enum):
    ACTIVE = "active"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecordingSource(str, enum.Enum):
    BROWSER_EXTENSION = "browser_extension"
    DESKTOP_AGENT = "desktop_agent"
    API = "api"


class SemanticActionType(str, enum.Enum):
    # Navigation
    NAVIGATE = "navigate"
    TAB_SWITCH = "tab_switch"

    # Browser interactions
    CLICK = "click"
    INPUT = "input"
    FORM_SUBMIT = "form_submit"
    SELECT = "select"
    SCROLL = "scroll"

    # File operations
    DOWNLOAD = "download"
    UPLOAD = "upload"
    FILE_CREATE = "file_create"
    FILE_RENAME = "file_rename"
    FILE_MOVE = "file_move"
    FILE_DELETE = "file_delete"

    # Data operations
    COPY = "copy"
    PASTE = "paste"
    EXTRACT_DATA = "extract_data"

    # Application-specific
    OPEN_EMAIL = "open_email"
    SEND_EMAIL = "send_email"
    DOWNLOAD_ATTACHMENT = "download_attachment"
    SEARCH = "search"

    # Compound (AI-inferred)
    ARCHIVE_DOCUMENT = "archive_document"
    FILL_FORM = "fill_form"
    LOGIN = "login"

    # Fallback
    UNKNOWN = "unknown"


class RecordingSession(Base):
    """
    A recording session initiated by the user.

    Tracks the lifecycle of a workflow recording from start to semantic conversion.
    """

    __tablename__ = "recording_sessions"

    # Session metadata
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[RecordingSource] = mapped_column(
        Enum(RecordingSource), default=RecordingSource.BROWSER_EXTENSION, nullable=False
    )
    status: Mapped[RecordingStatus] = mapped_column(
        Enum(RecordingStatus), default=RecordingStatus.ACTIVE, nullable=False
    )

    # Statistics
    raw_event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    semantic_action_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Error information
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Extra metadata (browser info, OS, extension version, etc.)
    # "metadata" is reserved on declarative classes, so the attribute is renamed; the column keeps its name
    session_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONType, nullable=True)

    # Relationships
    raw_events: Mapped[list[RawEvent]] = relationship(
        "RawEvent", back_populates="session", cascade="all, delete-orphan"
    )
    semantic_actions: Mapped[list[SemanticAction]] = relationship(
        "SemanticAction", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_recording_sessions_status", "status"),
        Index("ix_recording_sessions_created_at", "created_at"),
    )


class RawEvent(Base):
    """
    A raw browser/desktop event captured during a recording session.

    Raw events are low-level and include all captured metadata.
    They are converted to SemanticActions by the processing pipeline.
    """

    __tablename__ = "raw_events"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recording_sessions.id", ondelete="CASCADE"), nullable=False
    )

    # Event classification
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g., "click", "input", "navigation", "download", "copy"

    # Temporal ordering
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    client_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Unix ms (> 2^31)

    # Page context
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_title: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Element identification (semantic, not coordinates)
    element_tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    element_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    element_aria_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    element_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    element_placeholder: Mapped[str | None] = mapped_column(String(500), nullable=True)
    element_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    element_parent_context: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Value (for inputs, selects — sanitized to remove sensitive data)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full event payload as captured
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # Relationship
    session: Mapped[RecordingSession] = relationship("RecordingSession", back_populates="raw_events")

    __table_args__ = (
        Index("ix_raw_events_session_id", "session_id"),
        Index("ix_raw_events_sequence", "session_id", "sequence_number"),
    )


class SemanticAction(Base):
    """
    A high-level, intent-aware action derived from one or more raw events.

    This is the core unit of AutoFlow's intelligence layer.
    Instead of "click x=513 y=402", it stores "Download attachment from Gmail".
    """

    __tablename__ = "semantic_actions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recording_sessions.id", ondelete="CASCADE"), nullable=False
    )

    # Semantic classification
    action_type: Mapped[SemanticActionType] = mapped_column(
        Enum(SemanticActionType), nullable=False
    )

    # Human-readable description
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # e.g., "Downloaded invoice PDF from Gmail"

    # Ordering within the session
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Page/app context
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    application: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # e.g., "Gmail", "Google Drive", "Notion"

    # Extracted data (variables to parameterize)
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # e.g., {"filename": "Invoice-001.pdf", "client": "Acme Corp"}

    # Source raw event IDs
    raw_event_ids: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    # Confidence score from AI classification (0.0 - 1.0)
    confidence: Mapped[float | None] = mapped_column(nullable=True)

    # Relationship
    session: Mapped[RecordingSession] = relationship(
        "RecordingSession", back_populates="semantic_actions"
    )

    __table_args__ = (
        Index("ix_semantic_actions_session_id", "session_id"),
        Index("ix_semantic_actions_action_type", "action_type"),
    )
