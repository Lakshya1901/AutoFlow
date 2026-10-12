"""
Tests — Recording Sessions API
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_start_recording(client: AsyncClient) -> None:
    """Test starting a new recording session."""
    response = await client.post(
        "/api/v1/recordings/start",
        json={"name": "Test Recording", "source": "browser_extension"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Recording"
    assert data["status"] == "active"
    assert "id" in data


@pytest.mark.asyncio
async def test_ingest_events(client: AsyncClient) -> None:
    """Test ingesting a batch of raw events."""
    # Start a session
    start_response = await client.post(
        "/api/v1/recordings/start",
        json={"name": "Event Test"},
    )
    session_id = start_response.json()["id"]

    # Ingest events
    events = [
        {
            "event_type": "navigation",
            "sequence_number": 0,
            "client_timestamp": 1700000000000,
            "url": "https://mail.google.com",
            "page_title": "Gmail",
            "element": {"tag": "body", "role": None, "aria_label": None},
        },
        {
            "event_type": "click",
            "sequence_number": 1,
            "client_timestamp": 1700000001000,
            "url": "https://mail.google.com",
            "page_title": "Gmail",
            "element": {
                "tag": "span",
                "role": "link",
                "aria_label": None,
                "text": "Invoice from Acme Corp",
            },
        },
        {
            "event_type": "download",
            "sequence_number": 2,
            "client_timestamp": 1700000002000,
            "url": "https://mail.google.com",
        },
    ]

    ingest_response = await client.post(
        f"/api/v1/recordings/{session_id}/events",
        json={"events": events},
    )
    assert ingest_response.status_code == 200
    ingest_data = ingest_response.json()
    assert ingest_data["events_ingested"] == 3
    assert ingest_data["total_events"] == 3


@pytest.mark.asyncio
async def test_stop_recording_triggers_conversion(client: AsyncClient) -> None:
    """Test that stopping a recording triggers semantic conversion."""
    # Start session
    start_resp = await client.post(
        "/api/v1/recordings/start",
        json={"name": "Conversion Test"},
    )
    session_id = start_resp.json()["id"]

    # Ingest some events
    await client.post(
        f"/api/v1/recordings/{session_id}/events",
        json={
            "events": [
                {
                    "event_type": "navigation",
                    "sequence_number": 0,
                    "client_timestamp": 1700000000000,
                    "url": "https://mail.google.com",
                    "page_title": "Gmail",
                },
            ]
        },
    )

    # Stop recording
    stop_resp = await client.post(f"/api/v1/recordings/{session_id}/stop")
    assert stop_resp.status_code == 200
    data = stop_resp.json()
    assert data["status"] == "completed"
    assert len(data["semantic_actions"]) > 0
    # Should have at least one navigation action
    action_types = [a["action_type"] for a in data["semantic_actions"]]
    assert "navigate" in action_types


@pytest.mark.asyncio
async def test_list_recordings(client: AsyncClient) -> None:
    """Test listing recording sessions."""
    response = await client.get("/api/v1/recordings")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "has_more" in data


@pytest.mark.asyncio
async def test_get_recording_not_found(client: AsyncClient) -> None:
    """Test getting a non-existent recording returns 404."""
    response = await client.get("/api/v1/recordings/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_recording(client: AsyncClient) -> None:
    """Test deleting a recording."""
    create_resp = await client.post(
        "/api/v1/recordings/start",
        json={"name": "To Delete"},
    )
    session_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/recordings/{session_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/recordings/{session_id}")
    assert get_resp.status_code == 404
