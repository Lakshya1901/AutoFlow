"""
hsae_pipeline.py — Hierarchical Semantic Action Extraction Pipeline

Orchestrates all 4 layers of the HSAE pipeline into a single callable:

    Layer 1: EventPreprocessor  — filter noise, cluster, enrich DOM context
    Layer 2: ActionRecognizer   — rule-based action pattern matching
    Layer 3: IntentExtractor    — Gemini API intent inference (with fallback)
    Layer 4: WorkflowSynthesizer — convert to executable WorkflowDefinition

Usage:
    pipeline = HSAEPipeline()
    result = pipeline.run(raw_events, recording_id="rec_123")
    # result.workflow is a WorkflowDefinition ready to execute
    # result.actions is the list of SemanticAction objects
    # result.intent is the extracted intent dict

Entry point for the REST API in recordings/router.py:
    POST /recordings/{id}/extract  →  calls HSAEPipeline().run(events)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HSAEResult:
    """Output of the full HSAE pipeline."""
    recording_id: str
    raw_event_count: int
    filtered_event_count: int
    actions: list[Any]           # List[SemanticAction]
    intent: dict[str, Any]
    workflow: Any                # WorkflowDefinition
    processing_time_ms: float
    layer_times_ms: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class HSAEPipeline:
    """
    Orchestrates the full 4-layer HSAE pipeline.

    Layers are imported lazily so the pipeline degrades gracefully
    if any layer fails to import (e.g. Gemini API unavailable).

    Args:
        cluster_window_ms:  Temporal clustering window for Layer 1.
        min_action_confidence: Minimum confidence to include a SemanticAction.
        gemini_model:       Gemini model name for Layer 3.
    """

    def __init__(
        self,
        cluster_window_ms: int = 2000,
        min_action_confidence: float = 0.3,
        gemini_model: str = "gemini-2.0-flash",
    ):
        self.cluster_window_ms = cluster_window_ms
        self.min_action_confidence = min_action_confidence
        self.gemini_model = gemini_model
        self._preprocessor = None
        self._recognizer = None
        self._extractor = None
        self._synthesizer = None

    def _get_preprocessor(self):
        if self._preprocessor is None:
            try:
                from autoflow.recordings.preprocessor import EventPreprocessor
                self._preprocessor = EventPreprocessor(
                    cluster_window_ms=self.cluster_window_ms
                )
            except ImportError as e:
                logger.warning(f"EventPreprocessor unavailable: {e}")
        return self._preprocessor

    def _get_recognizer(self):
        if self._recognizer is None:
            try:
                from autoflow.recordings.action_recognizer import ActionRecognizer
                self._recognizer = ActionRecognizer()
            except ImportError as e:
                logger.warning(f"ActionRecognizer unavailable: {e}")
        return self._recognizer

    def _get_extractor(self):
        if self._extractor is None:
            try:
                from autoflow.ai.intent_extractor import IntentExtractor
                self._extractor = IntentExtractor(model=self.gemini_model)
            except ImportError as e:
                logger.warning(f"IntentExtractor unavailable: {e}")
        return self._extractor

    def _get_synthesizer(self):
        if self._synthesizer is None:
            try:
                from autoflow.recordings.synthesizer import WorkflowSynthesizer
                self._synthesizer = WorkflowSynthesizer()
            except ImportError as e:
                logger.warning(f"WorkflowSynthesizer unavailable: {e}")
        return self._synthesizer

    def run(self, raw_events: list[dict], recording_id: str = "") -> HSAEResult:
        """
        Run the full HSAE pipeline end-to-end.

        Args:
            raw_events:    List of raw browser event dicts from the Chrome extension.
            recording_id:  Identifier for the source recording.

        Returns:
            HSAEResult with workflow, actions, intent, and timing.
        """
        t_start = time.perf_counter()
        layer_times = {}
        errors = []
        n_raw = len(raw_events)

        # ── Layer 1: Preprocess ──────────────────────────────────────────
        t0 = time.perf_counter()
        preprocessor = self._get_preprocessor()
        if preprocessor:
            try:
                filtered_events = preprocessor.process(raw_events)
            except Exception as e:
                logger.error(f"Layer 1 failed: {e}")
                errors.append(f"L1: {e}")
                filtered_events = raw_events
        else:
            filtered_events = [e for e in raw_events
                               if e.get("type") not in ("scroll", "mousemove", "mouseover")]
        layer_times["L1_preprocess_ms"] = (time.perf_counter() - t0) * 1000
        n_filtered = len(filtered_events)
        logger.info(f"[HSAE] L1: {n_raw} → {n_filtered} events")

        # ── Layer 2: Action Recognition ──────────────────────────────────
        t0 = time.perf_counter()
        recognizer = self._get_recognizer()
        if recognizer:
            try:
                actions = [
                    a for a in recognizer.recognize(filtered_events)
                    if a.confidence >= self.min_action_confidence
                ]
            except Exception as e:
                logger.error(f"Layer 2 failed: {e}")
                errors.append(f"L2: {e}")
                actions = []
        else:
            actions = []
        layer_times["L2_recognize_ms"] = (time.perf_counter() - t0) * 1000
        logger.info(f"[HSAE] L2: {len(actions)} semantic actions recognized")

        # ── Layer 3: Intent Extraction ───────────────────────────────────
        t0 = time.perf_counter()
        extractor = self._get_extractor()
        if extractor and actions:
            try:
                intent = extractor.extract(actions)
            except Exception as e:
                logger.error(f"Layer 3 failed: {e}")
                errors.append(f"L3: {e}")
                intent = self._fallback_intent(actions)
        else:
            intent = self._fallback_intent(actions)
        layer_times["L3_intent_ms"] = (time.perf_counter() - t0) * 1000
        logger.info(f"[HSAE] L3: goal='{intent.get('high_level_goal', '?')}'")

        # ── Layer 4: Workflow Synthesis ──────────────────────────────────
        t0 = time.perf_counter()
        synthesizer = self._get_synthesizer()
        if synthesizer and actions:
            try:
                workflow = synthesizer.synthesize(actions, intent, recording_id)
            except Exception as e:
                logger.error(f"Layer 4 failed: {e}")
                errors.append(f"L4: {e}")
                workflow = None
        else:
            workflow = None
        layer_times["L4_synthesize_ms"] = (time.perf_counter() - t0) * 1000
        n_steps = len(workflow.steps) if workflow else 0
        logger.info(f"[HSAE] L4: {n_steps} workflow steps synthesized")

        total_ms = (time.perf_counter() - t_start) * 1000
        return HSAEResult(
            recording_id=recording_id,
            raw_event_count=n_raw,
            filtered_event_count=n_filtered,
            actions=actions,
            intent=intent,
            workflow=workflow,
            processing_time_ms=total_ms,
            layer_times_ms=layer_times,
            errors=errors,
        )

    @staticmethod
    def _fallback_intent(actions: list) -> dict:
        """Heuristic intent when Gemini is unavailable."""
        types = [getattr(a, "type", "unknown") for a in actions]
        goal = "Automate user workflow"
        if "form_fill" in types:
            goal = "Fill out a form"
        elif "navigation" in types and len(types) <= 3:
            goal = "Navigate to a page"
        elif "search" in types:
            goal = "Perform a search"
        elif "download" in types:
            goal = "Download a file"
        return {
            "high_level_goal": goal,
            "step_descriptions": [getattr(a, "description", str(a)) for a in actions],
            "detected_variables": {},
            "workflow_name": goal.replace(" ", "_").lower(),
            "confidence": 0.5,
            "action_intents": [],
        }


# ---------------------------------------------------------------------------
# Sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== HSAEPipeline — Integration Sanity Check ===\n")

    pipeline = HSAEPipeline()

    # Synthetic events (mimicking Chrome extension output)
    raw_events = [
        {"type": "navigation", "timestamp_ms": 1000, "url": "https://example.com/form",
         "element": {"tag": "body"}},
        {"type": "mousemove", "timestamp_ms": 1500, "url": "https://example.com/form",
         "element": {"tag": "div"}},
        {"type": "focus", "timestamp_ms": 2000, "url": "https://example.com/form",
         "element": {"tag": "input", "id": "name", "aria_label": "Full Name", "type": "text"}},
        {"type": "input", "timestamp_ms": 2300, "url": "https://example.com/form",
         "element": {"tag": "input", "id": "name", "aria_label": "Full Name", "value": "Lakshya"}},
        {"type": "blur", "timestamp_ms": 2600, "url": "https://example.com/form",
         "element": {"tag": "input", "id": "name", "aria_label": "Full Name"}},
        {"type": "focus", "timestamp_ms": 3000, "url": "https://example.com/form",
         "element": {"tag": "input", "id": "email", "aria_label": "Email", "type": "email"}},
        {"type": "input", "timestamp_ms": 3300, "url": "https://example.com/form",
         "element": {"tag": "input", "id": "email", "aria_label": "Email", "value": "lakshya@example.com"}},
        {"type": "blur", "timestamp_ms": 3600, "url": "https://example.com/form",
         "element": {"tag": "input", "id": "email", "aria_label": "Email"}},
        {"type": "click", "timestamp_ms": 4000, "url": "https://example.com/form",
         "element": {"tag": "button", "type": "submit", "text_content": "Submit"}},
        {"type": "scroll", "timestamp_ms": 4200, "url": "https://example.com/thanks",
         "element": {"tag": "body"}},
    ]

    result = pipeline.run(raw_events, recording_id="test_rec_001")

    print(f"Raw events:      {result.raw_event_count}")
    print(f"Filtered events: {result.filtered_event_count}")
    print(f"Actions found:   {len(result.actions)}")
    print(f"Goal:            {result.intent.get('high_level_goal', '?')}")
    print(f"Workflow steps:  {len(result.workflow.steps) if result.workflow else 'N/A (synthesizer not loaded)'}")
    print(f"Processing time: {result.processing_time_ms:.1f}ms")
    print(f"Layer times:     {result.layer_times_ms}")
    if result.errors:
        print(f"Errors:          {result.errors}")
    print("\n✓ HSAEPipeline sanity check complete.")
