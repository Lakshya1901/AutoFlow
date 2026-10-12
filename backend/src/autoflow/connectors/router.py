"""
Connectors Router — API for connector discovery and management.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from autoflow.connectors.base import registry

router = APIRouter()


class ConnectorSummary(BaseModel):
    connector_id: str
    display_name: str
    description: str
    action_count: int


class ConnectorDetail(ConnectorSummary):
    actions: list[dict[str, Any]]


@router.get("", response_model=list[ConnectorSummary], summary="List available connectors")
async def list_connectors() -> Any:
    """List all registered connectors available in this AutoFlow instance."""
    return [
        ConnectorSummary(
            connector_id=c.connector_id,
            display_name=c.display_name,
            description=c.description,
            action_count=len(c.actions),
        )
        for c in registry.all()
    ]


@router.get("/{connector_id}", response_model=ConnectorDetail, summary="Get connector details")
async def get_connector(connector_id: str) -> Any:
    """Get a connector's details including all available actions and their schemas."""
    connector = registry.get(connector_id)
    if not connector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector '{connector_id}' not found",
        )
    return ConnectorDetail(
        connector_id=connector.connector_id,
        display_name=connector.display_name,
        description=connector.description,
        action_count=len(connector.actions),
        actions=[
            {
                "name": a.name,
                "display_name": a.display_name,
                "description": a.description,
                "input_schema": a.input_schema,
                "output_schema": a.output_schema,
                "requires_auth": a.requires_auth,
                "is_destructive": a.is_destructive,
            }
            for a in connector.actions
        ],
    )
