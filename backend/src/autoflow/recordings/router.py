"""
Recordings Domain — API Router
REST endpoints + WebSocket for real-time event streaming.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from autoflow.core.database import get_db
from autoflow.core.security import optional_api_key
from autoflow.recordings.schemas import (
    HSAEExtractionResponse,
    IngestResponse,
    RawEventBatchCreate,
    RecordingSessionCreate,
    RecordingSessionListResponse,
    RecordingSessionResponse,
    RecordingSessionWithActions,
)
from autoflow.recordings.service import RecordingService
from autoflow.recordings.synthesizer import WorkflowSynthesizer

router = APIRouter()


# ─── Session Endpoints ────────────────────────────────────────────────────────

@router.post(
    "/start",
    response_model=RecordingSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new recording session",
)
async def start_recording(
    data: RecordingSessionCreate,
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(optional_api_key),
) -> Any:
    """
    Start a new recording session.

    The Chrome Extension calls this when the user clicks "Start Recording".
    Returns a session ID that must be used for all subsequent event ingestion calls.
    """
    service = RecordingService(db)
    session = await service.start_session(data)
    return session


@router.post(
    "/{session_id}/events",
    response_model=IngestResponse,
    summary="Ingest a batch of raw events",
)
async def ingest_events(
    session_id: uuid.UUID,
    batch: RawEventBatchCreate,
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(optional_api_key),
) -> Any:
    """
    Ingest a batch of raw browser events into an active recording session.

    The extension sends events in batches (every ~500ms or every 50 events)
    to reduce network overhead.
    """
    service = RecordingService(db)
    try:
        count = await service.ingest_events(session_id, batch)
        session = await service.get_session(session_id)
        return IngestResponse(
            session_id=session_id,
            events_ingested=count,
            total_events=session.raw_event_count if session else count,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/{session_id}/stop",
    response_model=RecordingSessionWithActions,
    summary="Stop recording and trigger semantic conversion",
)
async def stop_recording(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(optional_api_key),
) -> Any:
    """
    Stop the recording session and trigger the semantic conversion pipeline.

    This will:
    1. Mark the session as stopped
    2. Convert raw events to semantic actions (synchronously for MVP)
    3. Return the session with all semantic actions

    Note: For large recordings, conversion may take a few seconds.
    """
    service = RecordingService(db)
    try:
        await service.stop_session(session_id)
        return await service.get_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic conversion failed: {e}",
        )


@router.post(
    "/{session_id}/extract",
    response_model=HSAEExtractionResponse,
    summary="Run the HSAE pipeline and synthesize a workflow",
)
async def extract_workflow(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: str | None = Depends(optional_api_key),
) -> Any:
    """
    Run Hierarchical Semantic Action Extraction over the recording's raw events:
    preprocess → recognize actions → infer intent → synthesize an executable workflow.
    """
    service = RecordingService(db)
    try:
        result = await service.extract_workflow(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return HSAEExtractionResponse(
        recording_id=result.recording_id,
        raw_event_count=result.raw_event_count,
        filtered_event_count=result.filtered_event_count,
        actions=[a.to_dict() for a in result.actions],
        intent=result.intent,
        workflow=json.loads(WorkflowSynthesizer.to_json(result.workflow)) if result.workflow else None,
        processing_time_ms=result.processing_time_ms,
        layer_times_ms=result.layer_times_ms,
        errors=result.errors,
    )


@router.get(
    "/{session_id}",
    response_model=RecordingSessionWithActions,
    summary="Get a recording session with semantic actions",
)
async def get_recording(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a recording session by ID, including all semantic actions."""
    service = RecordingService(db)
    session = await service.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording session {session_id} not found",
        )
    return session


@router.get(
    "",
    response_model=RecordingSessionListResponse,
    summary="List all recording sessions",
)
async def list_recordings(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all recording sessions with pagination."""
    service = RecordingService(db)
    sessions, total = await service.list_sessions(page=page, page_size=page_size)
    return RecordingSessionListResponse(
        items=sessions,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a recording session",
)
async def delete_recording(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a recording session and all its associated events."""
    service = RecordingService(db)
    try:
        await service.delete_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ─── WebSocket Streaming ──────────────────────────────────────────────────────

# Active WebSocket connections for live recording feedback
_active_connections: dict[str, list[WebSocket]] = {}


@router.websocket("/{session_id}/stream")
async def recording_stream(
    session_id: uuid.UUID,
    websocket: WebSocket,
) -> None:
    """
    WebSocket endpoint for real-time recording feedback.

    The frontend connects here to get live updates as the user records:
    - Each event as it's ingested
    - Semantic actions as they're generated
    - Status changes (processing → completed)

    The Chrome Extension uses REST for event ingestion (more reliable).
    The frontend uses this WebSocket for live visualization.
    """
    session_key = str(session_id)
    await websocket.accept()

    # Register connection
    if session_key not in _active_connections:
        _active_connections[session_key] = []
    _active_connections[session_key].append(websocket)

    try:
        await websocket.send_json({
            "type": "connected",
            "data": {"session_id": session_key, "message": "Connected to recording stream"},
        })

        # Keep alive — the frontend sends pings
        while True:
            try:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    finally:
        if session_key in _active_connections:
            _active_connections[session_key].remove(websocket)
            if not _active_connections[session_key]:
                del _active_connections[session_key]


async def broadcast_to_session(session_id: uuid.UUID, message: dict[str, Any]) -> None:
    """Broadcast a message to all WebSocket clients watching a session."""
    session_key = str(session_id)
    if session_key not in _active_connections:
        return

    dead_connections = []
    for ws in _active_connections[session_key]:
        try:
            await ws.send_json(message)
        except Exception:
            dead_connections.append(ws)

    for ws in dead_connections:
        _active_connections[session_key].remove(ws)
