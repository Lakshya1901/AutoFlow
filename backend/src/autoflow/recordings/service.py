"""
Recordings Domain — Business Logic Service
Handles session management, event ingestion, and semantic conversion pipeline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from autoflow.core.events import (
    RecordingEventIngested,
    RecordingStarted,
    RecordingStopped,
    SemanticConversionCompleted,
    event_bus,
)
from autoflow.core.logging import get_logger
from autoflow.recordings.hsae_pipeline import HSAEPipeline, HSAEResult
from autoflow.recordings.models import (
    RawEvent,
    RecordingSession,
    RecordingStatus,
    SemanticAction,
    SemanticActionType,
)
from autoflow.recordings.schemas import (
    RawEventBatchCreate,
    RecordingSessionCreate,
)

logger = get_logger(__name__)


# ─── Application Detection ────────────────────────────────────────────────────

_URL_TO_APP: dict[str, str] = {
    "mail.google.com": "Gmail",
    "drive.google.com": "Google Drive",
    "docs.google.com": "Google Docs",
    "sheets.google.com": "Google Sheets",
    "notion.so": "Notion",
    "slack.com": "Slack",
    "discord.com": "Discord",
    "github.com": "GitHub",
    "dropbox.com": "Dropbox",
    "onedrive.live.com": "OneDrive",
    "app.hubspot.com": "HubSpot",
    "trello.com": "Trello",
    "asana.com": "Asana",
    "linear.app": "Linear",
    "figma.com": "Figma",
}


def _detect_application(url: str | None) -> str | None:
    """Detect the application name from the URL domain."""
    if not url:
        return None
    for domain, app in _URL_TO_APP.items():
        if domain in url:
            return app
    return None


# ─── Semantic Conversion Rules ────────────────────────────────────────────────

def _classify_event_type(event_type: str, element_role: str | None, element_text: str | None,
                          url: str | None, value: str | None) -> SemanticActionType:  # noqa: ARG001
    """
    Rule-based classification of raw events into semantic action types.
    For ambiguous cases, this returns UNKNOWN — the AI takes over.
    """
    event_type = event_type.lower()
    role = (element_role or "").lower()
    text = (element_text or "").lower()

    match event_type:
        case "navigation":
            return SemanticActionType.NAVIGATE
        case "tab_switch":
            return SemanticActionType.TAB_SWITCH
        case "download":
            return SemanticActionType.DOWNLOAD
        case "form_submit":
            return SemanticActionType.FORM_SUBMIT
        case "copy":
            return SemanticActionType.COPY
        case "paste":
            return SemanticActionType.PASTE
        case "click":
            if role in ("button", "link", "menuitem"):
                if "send" in text or "submit" in text:
                    return SemanticActionType.FORM_SUBMIT
                if "search" in text:
                    return SemanticActionType.SEARCH
                return SemanticActionType.CLICK
            return SemanticActionType.CLICK
        case "input":
            if role in ("searchbox", "search"):
                return SemanticActionType.SEARCH
            return SemanticActionType.INPUT
        case _:
            return SemanticActionType.UNKNOWN


def _build_description(
    action_type: SemanticActionType,
    element_aria_label: str | None,
    element_text: str | None,
    url: str | None,
    application: str | None,
    value: str | None,  # noqa: ARG001 - deliberately unused: values may be sensitive
) -> str:
    """Build a human-readable description for a semantic action."""
    app_context = f" in {application}" if application else ""

    match action_type:
        case SemanticActionType.NAVIGATE:
            return f"Navigated to {url or 'unknown URL'}"
        case SemanticActionType.DOWNLOAD:
            return f"Downloaded file{app_context}"
        case SemanticActionType.CLICK:
            label = element_aria_label or element_text or "element"
            return f"Clicked '{label}'{app_context}"
        case SemanticActionType.INPUT:
            label = element_aria_label or "field"
            # Don't include value — could be sensitive
            return f"Typed in '{label}'{app_context}"
        case SemanticActionType.FORM_SUBMIT:
            return f"Submitted form{app_context}"
        case SemanticActionType.SEARCH:
            return f"Searched{app_context}"
        case SemanticActionType.COPY:
            return f"Copied data{app_context}"
        case SemanticActionType.PASTE:
            return f"Pasted data{app_context}"
        case SemanticActionType.TAB_SWITCH:
            return f"Switched to {application or url or 'another tab'}"
        case _:
            return f"Performed action: {action_type.value}{app_context}"


# ─── HSAE Adapter ─────────────────────────────────────────────────────────────

# The extension calls a submit "form_submit"; the HSAE preprocessor expects "submit"
_HSAE_EVENT_TYPES = {"form_submit": "submit"}


def _to_hsae_event(event: RawEvent) -> dict[str, Any]:
    """Convert a stored RawEvent into the dict shape the HSAE pipeline consumes."""
    element = {
        "tag": event.element_tag,
        "role": event.element_role,
        "aria_label": event.element_aria_label,
        "text": event.element_text,
        "placeholder": event.element_placeholder,
        "id": event.element_id,
        "parent_context": event.element_parent_context,
        "value": event.value,
    }
    return {
        "type": _HSAE_EVENT_TYPES.get(event.event_type, event.event_type),
        "timestamp_ms": event.client_timestamp,
        "url": event.url,
        "page_title": event.page_title,
        "element": {k: v for k, v in element.items() if v is not None},
    }


# ─── Recording Service ────────────────────────────────────────────────────────

class RecordingService:
    """Business logic for recording sessions."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def start_session(self, data: RecordingSessionCreate) -> RecordingSession:
        """Create and persist a new recording session."""
        session = RecordingSession(
            name=data.name,
            description=data.description,
            source=data.source,
            status=RecordingStatus.ACTIVE,
            session_metadata=data.metadata,
        )
        self._db.add(session)
        await self._db.flush()  # Get the ID without committing

        await event_bus.publish(RecordingStarted(session_id=session.id))
        logger.info("Recording session started", session_id=str(session.id))
        return session

    async def ingest_events(
        self,
        session_id: uuid.UUID,
        batch: RawEventBatchCreate,
    ) -> int:
        """
        Ingest a batch of raw events from the extension.
        Returns the number of events ingested.
        """
        # Verify session exists and is active
        session = await self._get_session_or_raise(session_id)
        if session.status != RecordingStatus.ACTIVE:
            raise ValueError(f"Session {session_id} is not active (status: {session.status})")

        # Bulk insert events
        raw_events = [
            RawEvent(
                session_id=session_id,
                event_type=ev.event_type,
                sequence_number=ev.sequence_number,
                client_timestamp=ev.client_timestamp,
                url=ev.url,
                page_title=ev.page_title,
                element_tag=ev.element.tag if ev.element else None,
                element_role=ev.element.role if ev.element else None,
                element_aria_label=ev.element.aria_label if ev.element else None,
                element_text=ev.element.text if ev.element else None,
                element_placeholder=ev.element.placeholder if ev.element else None,
                element_id=ev.element.element_id if ev.element else None,
                element_parent_context=ev.element.parent_context if ev.element else None,
                value=ev.value,
                payload=ev.payload,
            )
            for ev in batch.events
        ]
        self._db.add_all(raw_events)

        # Update event count
        await self._db.execute(
            update(RecordingSession)
            .where(RecordingSession.id == session_id)
            .values(raw_event_count=RecordingSession.raw_event_count + len(raw_events))
        )

        await event_bus.publish(
            RecordingEventIngested(session_id=session_id, event_count=len(raw_events))
        )
        logger.debug("Events ingested", session_id=str(session_id), count=len(raw_events))
        return len(raw_events)

    async def stop_session(self, session_id: uuid.UUID) -> RecordingSession:
        """
        Stop a recording session and trigger the semantic conversion pipeline.
        """
        session = await self._get_session_or_raise(session_id)
        if session.status != RecordingStatus.ACTIVE:
            raise ValueError(f"Session {session_id} is not active")

        # Calculate duration
        duration = int((datetime.now(UTC) - session.created_at.replace(tzinfo=UTC)).total_seconds())

        # Mark as processing
        await self._db.execute(
            update(RecordingSession)
            .where(RecordingSession.id == session_id)
            .values(status=RecordingStatus.PROCESSING, duration_seconds=duration)
        )

        await event_bus.publish(
            RecordingStopped(session_id=session_id, total_events=session.raw_event_count)
        )

        logger.info("Recording session stopped, triggering conversion", session_id=str(session_id))

        # Run semantic conversion
        try:
            await self._convert_to_semantic(session_id)
        except Exception as e:
            logger.exception("Semantic conversion failed", session_id=str(session_id))
            await self._db.execute(
                update(RecordingSession)
                .where(RecordingSession.id == session_id)
                .values(status=RecordingStatus.FAILED, error_message=str(e))
            )
            raise

        # Refresh and return
        await self._db.refresh(session)
        return session

    async def _convert_to_semantic(self, session_id: uuid.UUID) -> None:
        """
        Convert raw events into semantic actions.

        Pipeline:
        1. Load raw events ordered by sequence
        2. Group events by temporal proximity and context
        3. Apply rule-based classification
        4. Create semantic action records
        5. Update session status to COMPLETED
        """
        # Load all raw events for this session
        result = await self._db.execute(
            select(RawEvent)
            .where(RawEvent.session_id == session_id)
            .order_by(RawEvent.sequence_number)
        )
        raw_events = result.scalars().all()

        if not raw_events:
            logger.warning("No raw events to convert", session_id=str(session_id))
            await self._db.execute(
                update(RecordingSession)
                .where(RecordingSession.id == session_id)
                .values(status=RecordingStatus.COMPLETED)
            )
            return

        # Group events into semantic actions
        semantic_actions: list[SemanticAction] = []
        action_groups = self._group_events(raw_events)

        for seq_num, event_group in enumerate(action_groups):
            primary = event_group[0]
            application = _detect_application(primary.url)
            action_type = _classify_event_type(
                primary.event_type,
                primary.element_role,
                primary.element_text,
                primary.url,
                primary.value,
            )
            description = _build_description(
                action_type,
                primary.element_aria_label,
                primary.element_text,
                primary.url,
                application,
                primary.value,
            )

            # Extract data from the events
            extracted_data = self._extract_data(event_group)

            semantic_actions.append(
                SemanticAction(
                    session_id=session_id,
                    action_type=action_type,
                    description=description,
                    sequence_number=seq_num,
                    url=primary.url,
                    application=application,
                    extracted_data=extracted_data,
                    raw_event_ids=[str(e.id) for e in event_group],
                    confidence=0.8,  # Rule-based confidence
                )
            )

        self._db.add_all(semantic_actions)

        # Update session to completed
        await self._db.execute(
            update(RecordingSession)
            .where(RecordingSession.id == session_id)
            .values(
                status=RecordingStatus.COMPLETED,
                semantic_action_count=len(semantic_actions),
            )
        )

        await event_bus.publish(
            SemanticConversionCompleted(
                session_id=session_id, action_count=len(semantic_actions)
            )
        )
        logger.info(
            "Semantic conversion complete",
            session_id=str(session_id),
            action_count=len(semantic_actions),
        )

    def _group_events(self, events: list[RawEvent]) -> list[list[RawEvent]]:
        """
        Group raw events into logical action clusters.

        Strategy:
        - Navigation events always start a new group
        - Events within 500ms of each other are grouped together
        - A new page URL always starts a new group
        """
        if not events:
            return []

        groups: list[list[RawEvent]] = []
        current_group: list[RawEvent] = [events[0]]
        TIME_THRESHOLD_MS = 500

        for i in range(1, len(events)):
            prev = events[i - 1]
            curr = events[i]

            time_gap = curr.client_timestamp - prev.client_timestamp
            url_changed = curr.url != prev.url
            is_navigation = curr.event_type in ("navigation", "tab_switch")

            if is_navigation or url_changed or time_gap > TIME_THRESHOLD_MS:
                groups.append(current_group)
                current_group = [curr]
            else:
                current_group.append(curr)

        if current_group:
            groups.append(current_group)

        return groups

    def _extract_data(self, events: list[RawEvent]) -> dict[str, Any] | None:
        """
        Extract meaningful data from an event group for variable detection.
        """
        data: dict[str, Any] = {}
        for event in events:
            if event.value:
                label = (
                    event.element_aria_label
                    or event.element_placeholder
                    or event.element_id
                    or event.event_type
                )
                data[label] = event.value
        return data if data else None

    async def extract_workflow(self, session_id: uuid.UUID) -> HSAEResult:
        """Run the 4-layer HSAE pipeline over a session's raw events."""
        await self._get_session_or_raise(session_id)
        result = await self._db.execute(
            select(RawEvent)
            .where(RawEvent.session_id == session_id)
            .order_by(RawEvent.sequence_number)
        )
        events = [_to_hsae_event(e) for e in result.scalars().all()]
        return HSAEPipeline().run(events, recording_id=str(session_id))

    async def get_session(self, session_id: uuid.UUID) -> RecordingSession | None:
        """Get a session by ID."""
        result = await self._db.execute(
            select(RecordingSession)
            .where(RecordingSession.id == session_id)
            .options(selectinload(RecordingSession.semantic_actions))
        )
        return result.scalar_one_or_none()

    async def list_sessions(
        self, page: int = 1, page_size: int = 20
    ) -> tuple[list[RecordingSession], int]:
        """List recording sessions with pagination."""
        offset = (page - 1) * page_size

        count_result = await self._db.execute(
            select(func.count()).select_from(RecordingSession)
        )
        total = count_result.scalar_one()

        result = await self._db.execute(
            select(RecordingSession)
            .order_by(RecordingSession.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        sessions = result.scalars().all()
        return list(sessions), total

    async def delete_session(self, session_id: uuid.UUID) -> bool:
        """Delete a recording session and all its events (cascade)."""
        session = await self._get_session_or_raise(session_id)
        await self._db.delete(session)
        return True

    async def _get_session_or_raise(self, session_id: uuid.UUID) -> RecordingSession:
        """Get a session or raise a ValueError."""
        result = await self._db.execute(
            select(RecordingSession).where(RecordingSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Recording session {session_id} not found")
        return session
