"""
AI Planner — API Router
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from autoflow.ai.llm_client import get_llm_client
from autoflow.ai.schemas import (
    AIHealthResponse,
    IntentExtractionRequest,
    IntentExtractionResponse,
    NaturalLanguageEditRequest,
    NaturalLanguageEditResponse,
    WorkflowGenerationRequest,
    WorkflowSuggestionResponse,
)
from autoflow.ai.service import AIService
from autoflow.core.database import get_db

router = APIRouter()


@router.post(
    "/extract-intent",
    response_model=IntentExtractionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Extract intent from a recording session",
)
async def extract_intent(
    request: IntentExtractionRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Analyze a recording session's semantic actions and extract the user's high-level intent.

    This calls the configured LLM (Ollama by default) to understand:
    - What the user was trying to accomplish
    - What variables were involved
    - What the workflow steps are at a semantic level
    """
    service = AIService(db)
    try:
        analysis = await service.extract_intent(request.session_id)
        return analysis
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Intent extraction failed: {e}",
        )


@router.post(
    "/generate-workflow",
    response_model=WorkflowSuggestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a workflow from an intent analysis",
)
async def generate_workflow(
    request: WorkflowGenerationRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Generate an executable workflow definition from an intent analysis.

    The generated workflow is a suggestion — the user reviews and edits it
    in the visual editor before it's saved as an active workflow.
    """
    service = AIService(db)
    try:
        suggestion = await service.generate_workflow(request.intent_analysis_id)
        return suggestion
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow generation failed: {e}",
        )


@router.post(
    "/natural-language-edit",
    response_model=NaturalLanguageEditResponse,
    summary="Edit a workflow using natural language",
)
async def natural_language_edit(
    request: NaturalLanguageEditRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Modify an existing workflow using a plain English instruction.

    Examples:
    - "Run this every weekday at 9am"
    - "Add an approval step before uploading"
    - "Only process invoices over $500"
    - "Send me a Slack notification when done"
    """
    from autoflow.workflows.service import WorkflowService

    # Get the current workflow definition
    wf_service = WorkflowService(db)
    workflow = await wf_service.get_workflow(request.workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {request.workflow_id} not found",
        )

    ai_service = AIService(db)
    try:
        updated = await ai_service.apply_natural_language_edit(
            workflow_id=request.workflow_id,
            workflow_definition=workflow.definition,
            instruction=request.instruction,
        )

        # Apply the update
        await wf_service.update_workflow_definition(request.workflow_id, updated)

        return NaturalLanguageEditResponse(
            workflow_id=request.workflow_id,
            instruction=request.instruction,
            changes_applied=updated.get("changes_summary", ["Workflow updated"]),
            updated_workflow=updated,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/health",
    response_model=AIHealthResponse,
    summary="Check AI provider health",
)
async def ai_health() -> Any:
    """
    Check if the configured AI provider is reachable and responding.
    Useful for verifying Ollama is running or API keys are valid.
    """
    client = get_llm_client()
    result = await client.health_check()
    return result


@router.get(
    "/analyses/{analysis_id}",
    response_model=IntentExtractionResponse,
    summary="Get an intent analysis by ID",
)
async def get_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a previously extracted intent analysis."""
    service = AIService(db)
    analysis = await service.get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intent analysis {analysis_id} not found",
        )
    return analysis


@router.get(
    "/suggestions/{suggestion_id}",
    response_model=WorkflowSuggestionResponse,
    summary="Get a workflow suggestion by ID",
)
async def get_suggestion(
    suggestion_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a previously generated workflow suggestion."""
    service = AIService(db)
    suggestion = await service.get_suggestion(suggestion_id)
    if not suggestion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow suggestion {suggestion_id} not found",
        )
    return suggestion
