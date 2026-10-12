"""
Tests — Workflow CRUD and Engine
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_workflow(client: AsyncClient) -> None:
    """Test creating a workflow."""
    response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "Archive Invoice",
            "description": "Download and archive client invoices",
            "trigger_type": "manual",
            "steps": [
                {
                    "step_key": "step_001",
                    "name": "Navigate to Gmail",
                    "step_type": "browser_navigate",
                    "config": {"url": "https://mail.google.com"},
                    "position": 0,
                }
            ],
            "variables": [
                {
                    "name": "client_name",
                    "description": "The client's company name",
                    "variable_type": "string",
                    "is_required": True,
                }
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Archive Invoice"
    assert data["status"] == "draft"
    assert len(data["steps"]) == 1
    assert len(data["variables"]) == 1


@pytest.mark.asyncio
async def test_list_workflows(client: AsyncClient) -> None:
    """Test listing workflows."""
    response = await client.get("/api/v1/workflows")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_workflow(client: AsyncClient) -> None:
    """Test getting a specific workflow."""
    # Create first
    create_resp = await client.post(
        "/api/v1/workflows",
        json={"name": "Test Get Workflow"},
    )
    workflow_id = create_resp.json()["id"]

    # Get it
    response = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == workflow_id
    assert data["name"] == "Test Get Workflow"


@pytest.mark.asyncio
async def test_update_workflow(client: AsyncClient) -> None:
    """Test updating workflow metadata."""
    create_resp = await client.post(
        "/api/v1/workflows",
        json={"name": "Original Name"},
    )
    workflow_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/v1/workflows/{workflow_id}",
        json={"name": "Updated Name", "description": "New description"},
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_clone_workflow(client: AsyncClient) -> None:
    """Test cloning a workflow."""
    create_resp = await client.post(
        "/api/v1/workflows",
        json={"name": "Original Workflow"},
    )
    workflow_id = create_resp.json()["id"]

    clone_resp = await client.post(
        f"/api/v1/workflows/{workflow_id}/clone",
        params={"new_name": "Cloned Workflow"},
    )
    assert clone_resp.status_code == 201
    data = clone_resp.json()
    assert data["name"] == "Cloned Workflow"
    assert data["id"] != workflow_id


@pytest.mark.asyncio
async def test_delete_workflow(client: AsyncClient) -> None:
    """Test deleting a workflow."""
    create_resp = await client.post(
        "/api/v1/workflows",
        json={"name": "To Delete"},
    )
    workflow_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/workflows/{workflow_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_workflow_not_found(client: AsyncClient) -> None:
    """Test 404 for non-existent workflow."""
    response = await client.get("/api/v1/workflows/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
