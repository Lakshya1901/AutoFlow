"""
Tests — HSAE pipeline (unit + API)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from autoflow.recordings.hsae_pipeline import HSAEPipeline

URL = "https://example.com/signup"


def _form_events() -> list[dict]:
    """A user opens a page, fills name + email, and submits (extension wire format)."""
    events = [
        ("navigation", 1_700_000_000_000, None, None),
        ("click", 1_700_000_002_000, {"tag": "input", "aria_label": "Full Name", "element_id": "name"}, None),
        ("input", 1_700_000_002_400, {"tag": "input", "aria_label": "Full Name", "element_id": "name"}, "Ada Lovelace"),
        ("click", 1_700_000_005_000, {"tag": "input", "aria_label": "Email", "element_id": "email"}, None),
        ("input", 1_700_000_005_400, {"tag": "input", "aria_label": "Email", "element_id": "email"}, "ada@example.com"),
        ("form_submit", 1_700_000_008_000, {"tag": "form", "aria_label": "Sign up"}, None),
    ]
    return [
        {"event_type": t, "sequence_number": i, "client_timestamp": ts, "url": URL,
         "page_title": "Sign up", "element": el, "value": value}
        for i, (t, ts, el, value) in enumerate(events)
    ]


def test_pipeline_recognizes_form_fill_and_synthesizes_steps() -> None:
    raw = [
        {"type": "navigation", "timestamp_ms": 1000, "url": URL, "element": {"tag": "body"}},
        {"type": "mousemove", "timestamp_ms": 1200, "url": URL, "element": {"tag": "div"}},
        {"type": "focus", "timestamp_ms": 2000, "url": URL, "element": {"tag": "input", "id": "email", "aria_label": "Email"}},
        {"type": "input", "timestamp_ms": 2300, "url": URL, "element": {"tag": "input", "id": "email", "aria_label": "Email", "value": "a@b.com"}},
        {"type": "blur", "timestamp_ms": 2600, "url": URL, "element": {"tag": "input", "id": "email", "aria_label": "Email"}},
    ]
    result = HSAEPipeline().run(raw, recording_id="unit")
    assert result.errors == []
    assert result.filtered_event_count < result.raw_event_count  # mousemove noise dropped
    assert {a.type for a in result.actions} >= {"navigation", "form_fill"}
    assert result.workflow is not None and len(result.workflow.steps) >= 2


def test_pipeline_handles_empty_recording() -> None:
    result = HSAEPipeline().run([], recording_id="empty")
    assert result.actions == []
    assert result.workflow is None


@pytest.mark.asyncio
async def test_extract_endpoint_returns_workflow(client: AsyncClient) -> None:
    start = await client.post("/api/v1/recordings/start", json={"name": "Signup"})
    session_id = start.json()["id"]
    ingest = await client.post(
        f"/api/v1/recordings/{session_id}/events", json={"events": _form_events()}
    )
    assert ingest.status_code in (200, 201), ingest.text

    response = await client.post(f"/api/v1/recordings/{session_id}/extract")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["raw_event_count"] == 6
    assert data["errors"] == []
    assert data["actions"], "expected at least one semantic action"
    assert data["workflow"]["steps"]
    assert data["intent"]["high_level_goal"]


@pytest.mark.asyncio
async def test_extract_unknown_recording_is_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/recordings/00000000-0000-0000-0000-000000000000/extract"
    )
    assert response.status_code == 404
