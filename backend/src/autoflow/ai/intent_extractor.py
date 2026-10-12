"""
AI - Intent Extractor
======================
Layer 3 of the Hierarchical Semantic Action Extraction (HSAE) pipeline.

Uses Google Gemini (via the ``google-genai`` SDK) to infer the high-level
user intent from a list of ``SemanticAction`` objects produced by
``ActionRecognizer``.

Graceful degradation:
    - If ``GEMINI_API_KEY`` is absent, always uses the heuristic fallback.
    - If the Gemini API call fails, falls back to the heuristic implementation.
    - The heuristic fallback is pure-Python and produces sensible results for
      common action sequences without any network round-trip.

Output schema (returned by ``extract``):
    {
        'high_level_goal': str,
        'step_descriptions': list[str],
        'detected_variables': dict,
        'workflow_name': str,
        'confidence': float,
        'action_intents': list[dict]   # [{action_idx, intent, can_parameterize}]
    }
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Avoid hard import at module level so the file works without google-genai
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import SemanticAction — soft import to avoid circular deps
# ---------------------------------------------------------------------------

try:
    from autoflow.recordings.action_recognizer import SemanticAction
except ImportError:
    # Standalone mode (running __main__ without the full package)
    from dataclasses import dataclass, field

    @dataclass
    class SemanticAction:  # type: ignore[no-redef]
        type: str
        description: str
        element_info: dict = field(default_factory=dict)
        confidence: float = 1.0
        timestamp_ms: int = 0
        raw_events: list = field(default_factory=list)
        variables: dict = field(default_factory=dict)

        def to_dict(self) -> dict:
            return {
                "type": self.type,
                "description": self.description,
                "element_info": self.element_info,
                "confidence": self.confidence,
                "timestamp_ms": self.timestamp_ms,
                "variables": self.variables,
            }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GOAL_TEMPLATES: dict[str, str] = {
    "navigation": "Browse to a target page",
    "form_fill": "Fill out a form",
    "click": "Interact with a UI element",
    "search": "Search for information",
    "download": "Download a file",
    "select": "Choose from a dropdown",
}

_NAME_CONJUNCTIONS = frozenset({"and", "then", "with", "via", "using", "after", "before"})

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "high_level_goal": {"type": "string"},
        "step_descriptions": {"type": "array", "items": {"type": "string"}},
        "detected_variables": {"type": "object"},
        "workflow_name": {"type": "string"},
        "confidence": {"type": "number"},
        "action_intents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_idx": {"type": "integer"},
                    "intent": {"type": "string"},
                    "can_parameterize": {"type": "boolean"},
                },
                "required": ["action_idx", "intent", "can_parameterize"],
            },
        },
    },
    "required": [
        "high_level_goal",
        "step_descriptions",
        "detected_variables",
        "workflow_name",
        "confidence",
        "action_intents",
    ],
}

_SYSTEM_PROMPT = """\
You are AutoFlow's intent inference engine. Given a numbered list of \
semantic browser actions, you infer the user's HIGH-LEVEL GOAL and \
produce a structured workflow description.

Rules:
- high_level_goal: one concise sentence (max 15 words) describing what \
  the user is trying to accomplish overall.
- workflow_name: a short CamelCase identifier (2-4 words, no spaces) \
  suitable as a workflow ID, e.g. "SubmitExpenseReport".
- step_descriptions: one plain-English sentence per action, in the same \
  order as the input. Keep each under 20 words.
- detected_variables: key-value pairs for any values that appear \
  parameterizable (emails, dates, amounts, names, filenames, etc.). \
  Use snake_case keys.
- action_intents: for each action (0-indexed), provide intent (purpose \
  of that specific step) and whether the step's value can be parameterized.
- confidence: 0.0–1.0 float — how certain you are about the inferred goal.

Respond ONLY with valid JSON matching the provided schema. No markdown.
"""


# ---------------------------------------------------------------------------
# IntentExtractor
# ---------------------------------------------------------------------------


class IntentExtractor:
    """
    Infer user intent from a ``SemanticAction`` list using Gemini.

    Parameters
    ----------
    model:
        Gemini model name (e.g. ``"gemini-2.0-flash"``). Used only when
        the API key is available.
    """

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        self.model = model
        self._api_key: str | None = os.environ.get("GEMINI_API_KEY")
        self._client = None  # Initialised lazily on first use

        if self._api_key:
            logger.info("IntentExtractor: Gemini API key found, LLM mode enabled (model=%s)", model)
        else:
            logger.warning(
                "IntentExtractor: GEMINI_API_KEY not set — heuristic fallback will always be used."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, actions: list[SemanticAction]) -> dict[str, Any]:
        """
        Infer high-level intent from a list of semantic actions.

        Tries Gemini first (if API key is present). Falls back gracefully
        to ``_heuristic_fallback`` on any error or missing key.

        Parameters
        ----------
        actions:
            Ordered list of ``SemanticAction`` objects from ``ActionRecognizer``.

        Returns
        -------
        dict
            Intent extraction result containing ``high_level_goal``,
            ``step_descriptions``, ``detected_variables``, ``workflow_name``,
            ``confidence``, and ``action_intents``.
        """
        if not actions:
            return self._empty_result()

        if not self._api_key:
            logger.debug("IntentExtractor: no API key, using heuristic fallback")
            return self._heuristic_fallback(actions)

        try:
            return self._extract_with_gemini(actions)
        except Exception as exc:
            logger.warning(
                "IntentExtractor: Gemini API call failed (%s), using heuristic fallback", exc
            )
            return self._heuristic_fallback(actions)

    # ------------------------------------------------------------------
    # Private - Gemini integration
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazily initialise the google-genai client."""
        if self._client is None:
            try:
                import google.generativeai as genai  # type: ignore[import-untyped]

                genai.configure(api_key=self._api_key)
                self._client = genai.GenerativeModel(
                    model_name=self.model,
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        response_schema=_JSON_SCHEMA,
                        temperature=0.2,
                    ),
                    system_instruction=_SYSTEM_PROMPT,
                )
                logger.debug("IntentExtractor: google-generativeai client initialised")
            except ImportError as exc:
                raise RuntimeError(
                    "google-generativeai is not installed. "
                    "Run: pip install google-generativeai"
                ) from exc
        return self._client

    def _extract_with_gemini(self, actions: list[SemanticAction]) -> dict[str, Any]:
        """
        Call Gemini with structured JSON output mode.

        Parameters
        ----------
        actions:
            List of semantic actions to analyse.

        Returns
        -------
        dict
            Parsed intent extraction result from Gemini.
        """
        prompt = self._build_prompt(actions)
        client = self._get_client()

        logger.debug("IntentExtractor: calling Gemini with %d actions", len(actions))
        response = client.generate_content(prompt)

        raw_text = response.text.strip()
        logger.debug("IntentExtractor: received %d chars from Gemini", len(raw_text))

        # Strip optional markdown fences (defensive)
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(lines[1:-1])

        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Gemini returned invalid JSON: {exc}") from exc

        self._validate_and_fill(result, actions)
        return result

    # ------------------------------------------------------------------
    # Private - prompt builder
    # ------------------------------------------------------------------

    def _build_prompt(self, actions: list[SemanticAction]) -> str:
        """
        Build the intent extraction prompt from a list of SemanticActions.

        Each action is formatted as:
            N. [type] description
               variables: {key: value, ...}

        Parameters
        ----------
        actions:
            Ordered list of SemanticAction objects.

        Returns
        -------
        str
            The fully assembled user-role prompt text.
        """
        lines: list[str] = [
            "Analyse the following browser automation recording and extract the user's intent.\n",
            "Actions (in order):",
        ]

        for idx, action in enumerate(actions):
            lines.append(f"  {idx + 1}. [{action.type.upper()}] {action.description}")
            if action.variables:
                # Show variables without the generic 'url'/'field' catch-alls
                meaningful = {
                    k: v for k, v in action.variables.items()
                    if k not in ("url", "field") and v
                }
                if meaningful:
                    lines.append(f"     variables: {json.dumps(meaningful)}")

        lines.append(
            "\nReturn a JSON object matching the provided schema. "
            "Be concise — workflow_name must be CamelCase with no spaces."
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private - heuristic fallback
    # ------------------------------------------------------------------

    def _heuristic_fallback(self, actions: list[SemanticAction]) -> dict[str, Any]:
        """
        Pure-Python intent extraction with no API calls.

        Works by:
        1. Counting action type frequencies.
        2. Identifying the dominant action type.
        3. Constructing a goal string from the dominant types.
        4. Collecting all variables across actions.
        5. Generating a CamelCase workflow name.

        Parameters
        ----------
        actions:
            Ordered list of SemanticAction objects.

        Returns
        -------
        dict
            Heuristic intent result with lower confidence than Gemini output.
        """
        # Count types
        type_counts: dict[str, int] = {}
        all_variables: dict[str, Any] = {}
        for action in actions:
            type_counts[action.type] = type_counts.get(action.type, 0) + 1
            # Merge variables, skip generic keys
            for k, v in action.variables.items():
                if k not in ("url", "field") and v:
                    all_variables[k] = v

        dominant_types = sorted(type_counts, key=type_counts.__getitem__, reverse=True)[:3]

        # Build goal
        goal_parts = [_GOAL_TEMPLATES.get(t, t.replace("_", " ").title()) for t in dominant_types]
        if len(goal_parts) == 1:
            high_level_goal = goal_parts[0]
        elif len(goal_parts) == 2:
            high_level_goal = f"{goal_parts[0]} and {goal_parts[1]}"
        else:
            high_level_goal = f"{goal_parts[0]}, {goal_parts[1]}, and {goal_parts[2]}"

        # Workflow name: title-case each dominant type word, concatenate
        name_tokens = []
        for t in dominant_types[:2]:
            for word in t.replace("_", " ").split():
                if word.lower() not in _NAME_CONJUNCTIONS:
                    name_tokens.append(word.title())
        workflow_name = "".join(name_tokens) or "AutoWorkflow"

        # Per-action step descriptions
        step_descriptions = [a.description for a in actions]

        # Per-action intents
        action_intents = []
        for idx, action in enumerate(actions):
            meaningful_vars = {k: v for k, v in action.variables.items() if k not in ("url", "field") and v}
            action_intents.append(
                {
                    "action_idx": idx,
                    "intent": _GOAL_TEMPLATES.get(action.type, action.type.replace("_", " ").title()),
                    "can_parameterize": bool(meaningful_vars),
                }
            )

        # Confidence: lower for heuristic; boosted by variable richness
        base_confidence = 0.55
        if all_variables:
            base_confidence += min(0.15, len(all_variables) * 0.03)

        return {
            "high_level_goal": high_level_goal,
            "step_descriptions": step_descriptions,
            "detected_variables": all_variables,
            "workflow_name": workflow_name,
            "confidence": round(base_confidence, 3),
            "action_intents": action_intents,
        }

    # ------------------------------------------------------------------
    # Private - utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        """Return a safe empty result when no actions are provided."""
        return {
            "high_level_goal": "No actions recorded",
            "step_descriptions": [],
            "detected_variables": {},
            "workflow_name": "EmptyWorkflow",
            "confidence": 0.0,
            "action_intents": [],
        }

    @staticmethod
    def _validate_and_fill(result: dict, actions: list[SemanticAction]) -> None:
        """
        Ensure all required keys are present in the Gemini result.

        Fills missing keys with heuristic values rather than raising.
        Modifies ``result`` in-place.
        """
        required_keys = [
            "high_level_goal",
            "step_descriptions",
            "detected_variables",
            "workflow_name",
            "confidence",
            "action_intents",
        ]
        for key in required_keys:
            if key not in result:
                logger.warning("IntentExtractor: Gemini result missing key '%s', filling default", key)
                defaults: dict[str, Any] = {
                    "high_level_goal": "Automate browser task",
                    "step_descriptions": [a.description for a in actions],
                    "detected_variables": {},
                    "workflow_name": "AutoWorkflow",
                    "confidence": 0.5,
                    "action_intents": [],
                }
                result[key] = defaults[key]


# ---------------------------------------------------------------------------
# __main__ - sanity check (no API key needed - uses heuristic fallback)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s - %(message)s")

    BASE_TS = int(time.time() * 1000)

    # Build a realistic action sequence without importing the full package
    actions = [
        SemanticAction(
            type="navigation",
            description="Navigate to https://expenses.corp.com/submit",
            element_info={"url": "https://expenses.corp.com/submit"},
            confidence=1.0,
            timestamp_ms=BASE_TS,
            variables={"url": "https://expenses.corp.com/submit"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Employee Name' with 'Alice Johnson'",
            element_info={"label": "Employee Name", "role": "textbox"},
            confidence=0.95,
            timestamp_ms=BASE_TS + 1000,
            variables={"employee_name": "Alice Johnson"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Expense Date' with '2024-01-15'",
            element_info={"label": "Expense Date", "role": "textbox"},
            confidence=0.95,
            timestamp_ms=BASE_TS + 2000,
            variables={"expense_date": "2024-01-15"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Amount' with '127.50'",
            element_info={"label": "Amount", "role": "spinbutton"},
            confidence=0.95,
            timestamp_ms=BASE_TS + 3000,
            variables={"amount": "127.50"},
        ),
        SemanticAction(
            type="select",
            description='Select "Travel" from \'Expense Category\'',
            element_info={"label": "Expense Category", "role": "listbox"},
            confidence=0.95,
            timestamp_ms=BASE_TS + 4000,
            variables={"category": "Travel"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Recipient Email' with 'manager@corp.com'",
            element_info={"label": "Recipient Email", "role": "textbox"},
            confidence=0.95,
            timestamp_ms=BASE_TS + 5000,
            variables={"recipient_email": "manager@corp.com"},
        ),
        SemanticAction(
            type="click",
            description='Click "Submit Expense" button',
            element_info={"role": "button", "accessible_name": "Submit Expense"},
            confidence=0.9,
            timestamp_ms=BASE_TS + 6000,
            variables={"button_label": "Submit Expense"},
        ),
    ]

    extractor = IntentExtractor(model="gemini-2.0-flash")
    result = extractor.extract(actions)

    print(f"\n{'='*65}")
    print("  IntentExtractor Sanity Check (heuristic fallback mode)")
    print(f"{'='*65}")
    print(f"\n  high_level_goal  : {result['high_level_goal']}")
    print(f"  workflow_name    : {result['workflow_name']}")
    print(f"  confidence       : {result['confidence']}")
    print("\n  detected_variables:")
    for k, v in result["detected_variables"].items():
        print(f"    {k}: {v!r}")

    print(f"\n  step_descriptions ({len(result['step_descriptions'])} steps):")
    for i, desc in enumerate(result["step_descriptions"]):
        intent = result["action_intents"][i] if i < len(result["action_intents"]) else {}
        can_p = intent.get("can_parameterize", False)
        print(f"    {i+1}. {desc}  [parameterizable={can_p}]")

    print(f"\n{'='*65}\n  IntentExtractor sanity check PASSED\n{'='*65}\n")
