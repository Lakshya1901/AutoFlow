"""
Recordings - Workflow Synthesizer
===================================
Layer 4 of the Hierarchical Semantic Action Extraction (HSAE) pipeline.

Converts the output of ``IntentExtractor`` (intent dict) and
``ActionRecognizer`` (SemanticAction list) into a structured
``WorkflowDefinition`` that can be executed by AutoFlow's execution engine.

Key capabilities:
    - Maps each SemanticAction to a ``WorkflowStep`` with selector priority.
    - Detects repeated action patterns and wraps them in loop steps.
    - Replaces detected variable values with ``{{variable_name}}`` placeholders.
    - Inserts ``wait`` steps after navigations to model realistic page-load gaps.
    - Generates element_selector dicts in ARIA-first priority order.
    - Full JSON serialization / deserialization round-trip.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Soft import of SemanticAction
# ---------------------------------------------------------------------------

try:
    from autoflow.recordings.action_recognizer import SemanticAction
except ImportError:
    from dataclasses import dataclass as _dc
    from dataclasses import field as _f

    @_dc
    class SemanticAction:  # type: ignore[no-redef]
        type: str
        description: str
        element_info: dict = _f(default_factory=dict)
        confidence: float = 1.0
        timestamp_ms: int = 0
        raw_events: list = _f(default_factory=list)
        variables: dict = _f(default_factory=dict)

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
# Data model
# ---------------------------------------------------------------------------


@dataclass
class WorkflowStep:
    """
    A single, executable step within an AutoFlow workflow.

    Attributes
    ----------
    id:
        Unique UUID string for this step.
    type:
        Step category: ``'navigate'`` | ``'fill'`` | ``'click'`` |
        ``'wait'`` | ``'loop'`` | ``'condition'`` | ``'select'`` |
        ``'download'`` | ``'search'``.
    description:
        Human-readable description of what this step does.
    element_selector:
        Priority-ordered dict of selector strategies and their values.
        Keys are tried in insertion order; first match wins during execution.
        Example::

            {
                "aria_role_name": '[role="button"][aria-label="Submit"]',
                "label": 'label[for="submit-btn"] + button',
                "data_testid": '[data-testid="submit-button"]',
                "css": '#submit-btn',
            }
    input_value:
        The value to type/select, or ``None`` for click/navigate steps.
        May contain ``{{variable_name}}`` placeholders.
    variable_ref:
        If this step's ``input_value`` is driven by a workflow variable,
        this holds the variable name (without braces).
    timeout_ms:
        Maximum time in milliseconds to wait for the element before failing.
    retry_count:
        Number of times to retry before marking the step as failed.
    loop_steps:
        Child steps (only populated for ``type='loop'`` steps).
    loop_count:
        Expected number of iterations (only for ``type='loop'`` steps).
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = "click"
    description: str = ""
    element_selector: dict = field(default_factory=dict)
    input_value: str | None = None
    variable_ref: str | None = None
    timeout_ms: int = 5000
    retry_count: int = 3
    loop_steps: list[WorkflowStep] = field(default_factory=list)
    loop_count: int | None = None


@dataclass
class WorkflowDefinition:
    """
    A complete, executable workflow derived from a recorded user session.

    Attributes
    ----------
    id:
        Unique UUID string.
    name:
        CamelCase workflow name (from intent extractor or auto-generated).
    description:
        Human-readable goal description.
    steps:
        Ordered list of ``WorkflowStep`` objects.
    variables:
        Dict mapping variable names to their default values. Values typed
        as ``{{variable_name}}`` in step ``input_value`` fields refer to
        these names.
    created_at:
        UTC timestamp of synthesis.
    source_recording_id:
        UUID of the originating recording session (if available).
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Workflow"
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    variables: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    source_recording_id: str | None = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

_VARIABLE_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")
_CAMEL_SPLIT_RE = re.compile(r"([A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|\d+|[a-z]+)")


def _action_type_to_step_type(action_type: str) -> str:
    """Map a SemanticAction type to a WorkflowStep type."""
    mapping = {
        "navigation": "navigate",
        "form_fill": "fill",
        "click": "click",
        "search": "search",
        "download": "download",
        "select": "select",
    }
    return mapping.get(action_type, "click")


def _build_selector(element_info: dict, action_type: str) -> dict[str, str]:
    """
    Build a priority-ordered selector dict for a workflow step.

    Priority (highest to lowest confidence):
        1. ARIA role + accessible name  -> attribute selector
        2. Label association            -> label[for=...] or aria-labelledby
        3. data-testid / data-*         -> attribute selector
        4. HTML id                      -> CSS id selector
        5. CSS class / tag              -> CSS fallback

    Parameters
    ----------
    element_info:
        SemanticAction.element_info dict with role, label, id, etc.
    action_type:
        The semantic action type (used to infer element role when absent).

    Returns
    -------
    dict
        Ordered selector dict; execution engine tries keys top-to-bottom.
    """
    selectors: dict[str, str] = {}

    role = (element_info.get("role") or "").lower()
    label = element_info.get("accessible_name") or element_info.get("label") or ""
    elem_id = element_info.get("id") or ""
    tag = (element_info.get("tag") or "").lower()
    href = element_info.get("href") or ""
    data_testid = element_info.get("data_testid") or ""

    # Infer role if missing
    if not role and action_type in ("click",) and tag == "button":
        role = "button"
    if not role and action_type == "form_fill":
        role = "textbox"
    if not role and action_type == "select":
        role = "listbox"

    # 1. ARIA role + accessible name
    if role and label:
        safe_label = label.replace('"', '\\"')
        selectors["aria_role_name"] = f'[role="{role}"][aria-label="{safe_label}"]'
    elif role:
        selectors["aria_role"] = f'[role="{role}"]'

    # 2. Label association
    if label and elem_id:
        selectors["label_for"] = f'label[for="{elem_id}"]'
    if label and not elem_id:
        safe_label = label.replace('"', '\\"')
        selectors["aria_label"] = f'[aria-label="{safe_label}"]'

    # 3. data-testid
    if data_testid:
        selectors["data_testid"] = f'[data-testid="{data_testid}"]'

    # 4. HTML id
    if elem_id:
        selectors["css_id"] = f"#{elem_id}"

    # 5. href (for links)
    if href and tag == "a":
        safe_href = href.replace('"', '\\"')
        selectors["href"] = f'a[href="{safe_href}"]'

    # 6. CSS tag fallback
    if tag:
        css = tag
        if label:
            safe_label = label.replace('"', '\\"')
            css += f'[aria-label="{safe_label}"]'
        elif elem_id:
            css += f"#{elem_id}"
        selectors["css"] = css

    return selectors


def _slugify(text: str) -> str:
    """Convert arbitrary text to a snake_case variable name."""
    text = re.sub(r"[^\w\s]", "", text.lower())
    text = re.sub(r"\s+", "_", text.strip())
    return text or "var"


def _detect_loops(actions: list[SemanticAction]) -> list[tuple[int, int, int]]:
    """
    Find repeated action pattern runs of 3 or more repetitions.

    Uses a simple sliding-window approach: compares consecutive action
    type sequences to find repeating blocks.

    Returns
    -------
    list[tuple[int, int, int]]
        List of (start_idx, end_idx_exclusive, repeat_count) tuples
        indicating ranges to collapse into loop steps.
        Ranges are non-overlapping.
    """
    loops: list[tuple[int, int, int]] = []
    n = len(actions)

    # Try pattern lengths from longest to shortest
    for pattern_len in range(n // 3, 0, -1):
        i = 0
        while i + pattern_len * 3 <= n:
            pattern_types = [a.type for a in actions[i: i + pattern_len]]
            repeats = 1
            j = i + pattern_len
            while j + pattern_len <= n:
                window = [a.type for a in actions[j: j + pattern_len]]
                if window == pattern_types:
                    repeats += 1
                    j += pattern_len
                else:
                    break

            if repeats >= 3:
                # Check this range doesn't overlap an existing loop
                span_end = i + pattern_len * repeats
                overlaps = any(
                    not (span_end <= s or i >= e)
                    for s, e, _ in loops
                )
                if not overlaps:
                    loops.append((i, span_end, repeats))
                    i = span_end
                    continue
            i += 1

    return loops


# ---------------------------------------------------------------------------
# WorkflowSynthesizer
# ---------------------------------------------------------------------------


class WorkflowSynthesizer:
    """
    Convert SemanticAction lists and intent dicts into WorkflowDefinitions.

    Usage
    -----
    ::

        synthesizer = WorkflowSynthesizer()
        workflow = synthesizer.synthesize(actions, intent, recording_id="abc-123")
        json_str = synthesizer.to_json(workflow)
        restored = WorkflowSynthesizer.from_json(json_str)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesize(
        self,
        actions: list[SemanticAction],
        intent: dict[str, Any],
        recording_id: str | None = None,
    ) -> WorkflowDefinition:
        """
        Build a ``WorkflowDefinition`` from semantic actions and intent.

        Processing stages:
            1. Collect all detected variables from intent + actions.
            2. Detect loop patterns in the action list.
            3. Convert each action (or loop group) to WorkflowSteps.
            4. Parameterize values detected as variables.
            5. Insert wait steps after navigate steps.

        Parameters
        ----------
        actions:
            Ordered list of ``SemanticAction`` objects.
        intent:
            Output dict from ``IntentExtractor.extract()``.
        recording_id:
            Optional recording session UUID to link back to the source.

        Returns
        -------
        WorkflowDefinition
            Ready-to-execute workflow definition.
        """
        # Stage 1: collect variables
        variables: dict[str, Any] = dict(intent.get("detected_variables") or {})
        for action in actions:
            for k, v in action.variables.items():
                if k not in ("url", "field") and v and k not in variables:
                    variables[k] = v

        # Stage 2: detect loops
        loop_ranges = _detect_loops(actions)
        loop_set: set[int] = set()
        for start, end, _ in loop_ranges:
            loop_set.update(range(start, end))

        # Stage 3+4+5: build steps
        steps: list[WorkflowStep] = []
        i = 0
        while i < len(actions):
            # Check if this index starts a loop range
            matching_loop = next((lr for lr in loop_ranges if lr[0] == i), None)
            if matching_loop:
                start, end, repeat_count = matching_loop
                loop_action_group = actions[start: start + (end - start) // repeat_count]
                loop_step = self._make_loop_step(
                    loop_action_group, repeat_count, variables
                )
                steps.append(loop_step)
                i = end
                continue

            action = actions[i]
            step = self._action_to_step(action, variables)
            steps.append(step)

            # Insert wait after navigate
            if action.type == "navigation":
                steps.append(
                    WorkflowStep(
                        type="wait",
                        description="Wait for page to load after navigation",
                        element_selector={},
                        input_value=None,
                        timeout_ms=5000,
                        retry_count=0,
                    )
                )

            i += 1

        workflow_name = intent.get("workflow_name") or "AutoWorkflow"
        description = intent.get("high_level_goal") or "Automated workflow"

        return WorkflowDefinition(
            name=workflow_name,
            description=description,
            steps=steps,
            variables=variables,
            created_at=datetime.utcnow(),
            source_recording_id=recording_id,
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def to_json(workflow: WorkflowDefinition) -> str:
        """
        Serialize a ``WorkflowDefinition`` to a JSON string.

        ``datetime`` objects are converted to ISO-8601 strings.
        ``WorkflowStep`` objects nested in loop steps are handled
        recursively.

        Parameters
        ----------
        workflow:
            The WorkflowDefinition to serialize.

        Returns
        -------
        str
            Pretty-printed JSON string.
        """

        def _step_to_dict(step: WorkflowStep) -> dict:
            d = asdict(step)
            # Recursively handle loop_steps
            d["loop_steps"] = [_step_to_dict(s) for s in step.loop_steps]
            return d

        def _serialize(obj: Any) -> Any:
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        data = {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "steps": [_step_to_dict(s) for s in workflow.steps],
            "variables": workflow.variables,
            "created_at": workflow.created_at.isoformat(),
            "source_recording_id": workflow.source_recording_id,
        }
        return json.dumps(data, indent=2, default=_serialize)

    @staticmethod
    def from_json(json_str: str) -> WorkflowDefinition:
        """
        Deserialize a ``WorkflowDefinition`` from a JSON string.

        Parameters
        ----------
        json_str:
            JSON produced by ``to_json()``.

        Returns
        -------
        WorkflowDefinition
        """

        def _dict_to_step(d: dict) -> WorkflowStep:
            loop_steps = [_dict_to_step(s) for s in d.pop("loop_steps", [])]
            return WorkflowStep(**{**d, "loop_steps": loop_steps})

        data = json.loads(json_str)
        steps = [_dict_to_step(s) for s in data.pop("steps", [])]
        created_at_raw = data.pop("created_at", None)
        created_at = (
            datetime.fromisoformat(created_at_raw) if created_at_raw else datetime.utcnow()
        )
        return WorkflowDefinition(**{**data, "steps": steps, "created_at": created_at})

    # ------------------------------------------------------------------
    # Private - step construction
    # ------------------------------------------------------------------

    def _action_to_step(
        self,
        action: SemanticAction,
        variables: dict[str, Any],
    ) -> WorkflowStep:
        """
        Convert a single ``SemanticAction`` to a ``WorkflowStep``.

        Handles parameterization: if the action's input_value matches
        a known variable's value, replaces it with ``{{variable_name}}``.

        Parameters
        ----------
        action:
            The semantic action to convert.
        variables:
            All workflow variables (used for parameterization).

        Returns
        -------
        WorkflowStep
        """
        step_type = _action_type_to_step_type(action.type)
        selector = _build_selector(action.element_info, action.type)

        input_value: str | None = None
        variable_ref: str | None = None
        timeout_ms = 5000
        retry_count = 3

        if action.type == "navigation":
            url = action.variables.get("url") or action.element_info.get("url") or ""
            input_value, variable_ref = self._parameterize(url, variables)
            timeout_ms = 10000  # navigations need more time
            retry_count = 2

        elif action.type == "form_fill":
            # Use the variable that is NOT 'field' (the actual typed value)
            value = ""
            for k, v in action.variables.items():
                if k != "field" and v:
                    value = str(v)
                    break
            input_value, variable_ref = self._parameterize(value, variables)

        elif action.type == "search":
            query = action.variables.get("query") or ""
            input_value, variable_ref = self._parameterize(query, variables)

        elif action.type == "select":
            selection = action.variables.get("selection") or ""
            input_value, variable_ref = self._parameterize(selection, variables)

        elif action.type == "download":
            href = action.variables.get("download_url") or ""
            input_value, variable_ref = self._parameterize(href, variables)

        return WorkflowStep(
            type=step_type,
            description=action.description,
            element_selector=selector,
            input_value=input_value,
            variable_ref=variable_ref,
            timeout_ms=timeout_ms,
            retry_count=retry_count,
        )

    def _make_loop_step(
        self,
        pattern_actions: list[SemanticAction],
        repeat_count: int,
        variables: dict[str, Any],
    ) -> WorkflowStep:
        """
        Wrap a repeated action pattern into a single loop WorkflowStep.

        Parameters
        ----------
        pattern_actions:
            The actions forming a single loop iteration.
        repeat_count:
            Number of iterations detected.
        variables:
            Workflow variable dict for parameterization.

        Returns
        -------
        WorkflowStep
            A step of type ``'loop'`` with child steps.
        """
        child_steps = [self._action_to_step(a, variables) for a in pattern_actions]
        description = (
            f"Repeat {repeat_count}x: "
            + ", ".join(a.description for a in pattern_actions[:2])
            + ("..." if len(pattern_actions) > 2 else "")
        )
        return WorkflowStep(
            type="loop",
            description=description,
            element_selector={},
            input_value=None,
            variable_ref=None,
            timeout_ms=0,
            retry_count=0,
            loop_steps=child_steps,
            loop_count=repeat_count,
        )

    @staticmethod
    def _parameterize(
        value: str,
        variables: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        """
        Replace a concrete value with a variable placeholder if it matches.

        Searches the variables dict for any entry whose value equals
        ``value``. If found, returns ``("{{var_name}}", "var_name")``.
        Otherwise returns the original value unchanged.

        Parameters
        ----------
        value:
            The raw string value to potentially parameterize.
        variables:
            Dict of variable name -> default value.

        Returns
        -------
        tuple[Optional[str], Optional[str]]
            (input_value, variable_ref) pair.
        """
        if not value:
            return None, None

        for var_name, var_value in variables.items():
            if str(var_value) == str(value):
                return f"{{{{{var_name}}}}}", var_name

        return value, None


# ---------------------------------------------------------------------------
# __main__ - sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import time

    BASE_TS = int(time.time() * 1000)

    # Build a sample action sequence (expense report)
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
            element_info={"tag": "input", "id": "emp-name", "role": "textbox", "label": "Employee Name", "accessible_name": "Employee Name"},
            confidence=0.95,
            timestamp_ms=BASE_TS + 1000,
            variables={"field": "Employee Name", "employee_name": "Alice Johnson"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Expense Date' with '2024-01-15'",
            element_info={"tag": "input", "id": "exp-date", "role": "textbox", "label": "Expense Date", "accessible_name": "Expense Date"},
            confidence=0.95,
            timestamp_ms=BASE_TS + 2000,
            variables={"field": "Expense Date", "expense_date": "2024-01-15"},
        ),
        SemanticAction(
            type="select",
            description='Select "Travel" from \'Category\'',
            element_info={"tag": "select", "id": "category", "role": "listbox", "label": "Category", "accessible_name": "Category"},
            confidence=0.95,
            timestamp_ms=BASE_TS + 3000,
            variables={"field": "Category", "selection": "Travel"},
        ),
        # Repeat the row-fill pattern 3x to trigger loop detection
        SemanticAction(
            type="form_fill",
            description="Fill 'Item 1 Description' with 'Flight NYC'",
            element_info={"tag": "input", "id": "item-desc-1", "role": "textbox", "label": "Item Description"},
            confidence=0.9,
            timestamp_ms=BASE_TS + 4000,
            variables={"field": "Item Description", "item_description": "Flight NYC"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Item 1 Amount' with '320.00'",
            element_info={"tag": "input", "id": "item-amt-1", "role": "spinbutton", "label": "Item Amount"},
            confidence=0.9,
            timestamp_ms=BASE_TS + 4500,
            variables={"field": "Item Amount", "item_amount": "320.00"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Item 2 Description' with 'Hotel stay'",
            element_info={"tag": "input", "id": "item-desc-2", "role": "textbox", "label": "Item Description"},
            confidence=0.9,
            timestamp_ms=BASE_TS + 5000,
            variables={"field": "Item Description", "item_description": "Hotel stay"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Item 2 Amount' with '450.00'",
            element_info={"tag": "input", "id": "item-amt-2", "role": "spinbutton", "label": "Item Amount"},
            confidence=0.9,
            timestamp_ms=BASE_TS + 5500,
            variables={"field": "Item Amount", "item_amount": "450.00"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Item 3 Description' with 'Taxi rides'",
            element_info={"tag": "input", "id": "item-desc-3", "role": "textbox", "label": "Item Description"},
            confidence=0.9,
            timestamp_ms=BASE_TS + 6000,
            variables={"field": "Item Description", "item_description": "Taxi rides"},
        ),
        SemanticAction(
            type="form_fill",
            description="Fill 'Item 3 Amount' with '87.50'",
            element_info={"tag": "input", "id": "item-amt-3", "role": "spinbutton", "label": "Item Amount"},
            confidence=0.9,
            timestamp_ms=BASE_TS + 6500,
            variables={"field": "Item Amount", "item_amount": "87.50"},
        ),
        SemanticAction(
            type="click",
            description='Click "Submit Expense" button',
            element_info={"tag": "button", "id": "submit-btn", "role": "button", "accessible_name": "Submit Expense"},
            confidence=0.9,
            timestamp_ms=BASE_TS + 7000,
            variables={"button_label": "Submit Expense"},
        ),
    ]

    intent = {
        "high_level_goal": "Submit an expense report with line items",
        "workflow_name": "SubmitExpenseReport",
        "detected_variables": {
            "employee_name": "Alice Johnson",
            "expense_date": "2024-01-15",
        },
        "confidence": 0.9,
    }

    synthesizer = WorkflowSynthesizer()
    workflow = synthesizer.synthesize(actions, intent, recording_id="rec-test-001")

    print(f"\n{'='*65}")
    print("  WorkflowSynthesizer Sanity Check")
    print(f"{'='*65}")
    print(f"  Workflow ID  : {workflow.id}")
    print(f"  Name         : {workflow.name}")
    print(f"  Description  : {workflow.description}")
    print(f"  Steps total  : {len(workflow.steps)}")
    print(f"  Variables    : {list(workflow.variables.keys())}")
    print()

    for i, step in enumerate(workflow.steps):
        loop_info = f" [loop x{step.loop_count}, {len(step.loop_steps)} child steps]" if step.type == "loop" else ""
        var_info = f" -> {{{{ {step.variable_ref} }}}}" if step.variable_ref else ""
        print(
            f"  [{i+1:02d}] {step.type:<10} "
            f"val={step.input_value!s:<25} "
            f"{var_info}"
            f"\"{step.description[:55]}\""
            f"{loop_info}"
        )

    # JSON round-trip test
    json_str = WorkflowSynthesizer.to_json(workflow)
    restored = WorkflowSynthesizer.from_json(json_str)
    assert restored.name == workflow.name, "Name mismatch after JSON round-trip!"
    assert len(restored.steps) == len(workflow.steps), "Step count mismatch after JSON round-trip!"
    print(f"\n  JSON round-trip: OK ({len(json_str)} chars)")
    print(f"\n{'='*65}\n  WorkflowSynthesizer sanity check PASSED\n{'='*65}\n")
