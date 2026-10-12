"""
AI Planner — Business Logic Service
Intent extraction, workflow generation, and natural language editing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from autoflow.ai.llm_client import LLMClient, get_llm_client
from autoflow.ai.models import IntentAnalysis, WorkflowSuggestion
from autoflow.ai.prompts import (
    render_intent_extraction_prompt,
    render_natural_language_edit_prompt,
    render_workflow_generation_prompt,
)
from autoflow.core.config import get_settings
from autoflow.core.events import IntentExtractionCompleted, event_bus
from autoflow.core.logging import get_logger
from autoflow.recordings.models import RecordingSession

logger = get_logger(__name__)


class AIService:
    """
    AI Planner service — the intelligence layer of AutoFlow.

    Responsibilities:
    - Extract intent from recorded semantic actions
    - Generate executable workflow definitions
    - Support natural language workflow editing
    """

    def __init__(self, db: AsyncSession, llm: LLMClient | None = None) -> None:
        self._db = db
        self._llm = llm or get_llm_client()
        self._settings = get_settings()

    async def extract_intent(self, session_id: uuid.UUID) -> IntentAnalysis:
        """
        Extract user intent from a completed recording session.

        Uses the LLM to analyze semantic actions and infer the user's goal.
        Returns a structured IntentAnalysis record.
        """
        # Load the session with its semantic actions
        result = await self._db.execute(
            select(RecordingSession)
            .where(RecordingSession.id == session_id)
            .options(selectinload(RecordingSession.semantic_actions))
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Recording session {session_id} not found")

        if not session.semantic_actions:
            raise ValueError(f"Session {session_id} has no semantic actions to analyze")

        # Build action list for the prompt
        actions = [
            {
                "type": action.action_type.value,
                "description": action.description,
                "application": action.application,
                "url": action.url,
                "extracted_data": action.extracted_data,
            }
            for action in sorted(session.semantic_actions, key=lambda a: a.sequence_number)
        ]

        applications = [a.get("application") for a in actions if a.get("application")]

        # Build and send prompt
        messages = render_intent_extraction_prompt(
            actions=actions,
            duration_seconds=session.duration_seconds or 0,
            applications=applications,
        )

        logger.info(
            "Extracting intent from recording",
            session_id=str(session_id),
            action_count=len(actions),
        )

        llm_response = await self._llm.complete(
            messages,
            response_format="json",
            temperature=0.1,
        )

        # Parse the structured response
        try:
            parsed = llm_response.parse_json()
        except ValueError as e:
            logger.error("Failed to parse intent extraction response", error=str(e))
            raise ValueError(f"AI returned invalid JSON: {e}") from e

        # Create the IntentAnalysis record
        analysis = IntentAnalysis(
            session_id=session_id,
            intent=parsed.get("intent", "Unknown intent"),
            goal_summary=parsed.get("goal_summary", ""),
            steps_summary=parsed.get("steps_summary"),
            detected_variables=parsed.get("detected_variables"),
            suggested_name=parsed.get("suggested_automation_name"),
            notes=parsed.get("notes"),
            confidence=float(parsed.get("confidence", 0.5)),
            ai_provider=self._settings.ai_provider.value,
            ai_model=self._settings.resolved_ai_model,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            raw_response=parsed,
        )

        self._db.add(analysis)
        await self._db.flush()

        await event_bus.publish(
            IntentExtractionCompleted(
                session_id=session_id,
                intent=analysis.intent,
                confidence=analysis.confidence,
            )
        )

        logger.info(
            "Intent extraction complete",
            session_id=str(session_id),
            intent=analysis.intent,
            confidence=analysis.confidence,
        )

        return analysis

    async def generate_workflow(self, intent_analysis_id: uuid.UUID) -> WorkflowSuggestion:
        """
        Generate an executable workflow definition from an intent analysis.
        """
        # Load the intent analysis
        result = await self._db.execute(
            select(IntentAnalysis).where(IntentAnalysis.id == intent_analysis_id)
        )
        analysis = result.scalar_one_or_none()
        if not analysis:
            raise ValueError(f"Intent analysis {intent_analysis_id} not found")

        # Load original session actions for context
        session_result = await self._db.execute(
            select(RecordingSession)
            .where(RecordingSession.id == analysis.session_id)
            .options(selectinload(RecordingSession.semantic_actions))
        )
        session = session_result.scalar_one_or_none()
        actions = []
        if session and session.semantic_actions:
            actions = [
                {"type": a.action_type.value, "description": a.description}
                for a in sorted(session.semantic_actions, key=lambda x: x.sequence_number)
            ]

        messages = render_workflow_generation_prompt(
            intent=analysis.intent,
            goal_summary=analysis.goal_summary,
            steps_summary=analysis.steps_summary or [],
            variables=analysis.detected_variables or [],
            actions=actions,
        )

        logger.info(
            "Generating workflow from intent",
            analysis_id=str(intent_analysis_id),
            intent=analysis.intent,
        )

        llm_response = await self._llm.complete(
            messages,
            response_format="json",
            temperature=0.1,
            max_tokens=6000,
        )

        try:
            workflow_def = llm_response.parse_json()
        except ValueError as e:
            raise ValueError(f"AI returned invalid workflow JSON: {e}") from e

        # Create the workflow suggestion
        suggestion = WorkflowSuggestion(
            session_id=analysis.session_id,
            intent_analysis_id=intent_analysis_id,
            workflow_definition=workflow_def,
            accepted=False,
            ai_provider=self._settings.ai_provider.value,
            ai_model=self._settings.resolved_ai_model,
        )

        self._db.add(suggestion)
        await self._db.flush()

        logger.info(
            "Workflow suggestion generated",
            suggestion_id=str(suggestion.id),
            workflow_name=workflow_def.get("name", "Unnamed"),
            step_count=len(workflow_def.get("steps", [])),
        )

        return suggestion

    async def apply_natural_language_edit(
        self,
        workflow_id: uuid.UUID,
        workflow_definition: dict[str, Any],
        instruction: str,
    ) -> dict[str, Any]:
        """
        Apply a natural language edit instruction to a workflow definition.
        Returns the updated workflow definition.
        """
        messages = render_natural_language_edit_prompt(
            instruction=instruction,
            workflow=workflow_definition,
        )

        logger.info(
            "Applying NL edit to workflow",
            workflow_id=str(workflow_id),
            instruction=instruction[:100],
        )

        llm_response = await self._llm.complete(
            messages,
            response_format="json",
            temperature=0.1,
        )

        try:
            edit_result = llm_response.parse_json()
        except ValueError as e:
            raise ValueError(f"AI returned invalid edit JSON: {e}") from e

        # The LLM should return the updated workflow_definition
        updated = edit_result.get("updated_workflow_definition") or edit_result
        return updated

    async def get_analysis(self, analysis_id: uuid.UUID) -> IntentAnalysis | None:
        """Get an intent analysis by ID."""
        result = await self._db.execute(
            select(IntentAnalysis).where(IntentAnalysis.id == analysis_id)
        )
        return result.scalar_one_or_none()

    async def get_suggestion(self, suggestion_id: uuid.UUID) -> WorkflowSuggestion | None:
        """Get a workflow suggestion by ID."""
        result = await self._db.execute(
            select(WorkflowSuggestion).where(WorkflowSuggestion.id == suggestion_id)
        )
        return result.scalar_one_or_none()
