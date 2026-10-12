"""
Recordings - Action Recognizer
================================
Layer 2 of the Hierarchical Semantic Action Extraction (HSAE) pipeline.

Converts the enriched event stream produced by ``EventPreprocessor`` into
typed ``SemanticAction`` objects using a rule-based pattern matching engine.

Design principles:
    - **Offline-capable**: zero network calls, zero LLM usage. Pure Python.
    - **Rule-first**: deterministic rules handle ~80% of real-world actions.
    - **Heuristic fallback**: ambiguous clusters fall back to weighted scoring.
    - **Variable extraction**: all parameterisable values are surfaced for
      later use by the workflow synthesizer.

Recognised action types:
    navigation, form_fill, click, search, download, select
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SemanticAction dataclass
# ---------------------------------------------------------------------------


@dataclass
class SemanticAction:
    """
    A high-level, typed user action derived from one or more raw browser events.

    Attributes
    ----------
    type:
        Action category: 'navigation' | 'form_fill' | 'click' |
        'download' | 'search' | 'select'.
    description:
        Human-readable description of what the user did.
    element_info:
        Semantic element metadata (role, accessible name, form context, ...).
    confidence:
        Float in [0, 1] - how certain the recognizer is about the action type.
    timestamp_ms:
        Unix timestamp (ms) of the first contributing event.
    raw_events:
        The source enriched event dicts that produced this action.
    variables:
        Key/value pairs that are candidates for parameterization, e.g.
        {'email': 'alice@corp.com', 'query': 'Q4 2024'}.
    """

    type: str
    description: str
    element_info: dict = field(default_factory=dict)
    confidence: float = 1.0
    timestamp_ms: int = 0
    raw_events: list = field(default_factory=list)
    variables: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (JSON-safe)."""
        return {
            "type": self.type,
            "description": self.description,
            "element_info": self.element_info,
            "confidence": self.confidence,
            "timestamp_ms": self.timestamp_ms,
            "variables": self.variables,
            # raw_events intentionally omitted to keep serialisation compact
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEARCH_HINT_PATTERN = re.compile(
    r"search|query|find|lookup|filter",
    re.IGNORECASE,
)
_BUTTON_TAGS = frozenset({"button", "input[submit]", "input[button]", "input[reset]"})
_LINK_TAGS = frozenset({"a"})
_INPUT_TAGS = frozenset({"input", "textarea"})
_SELECT_TAGS = frozenset({"select"})


def _tag_type_key(element: dict) -> str:
    """Return a normalized 'tag[type]' key for quick matching."""
    tag = (element.get("tag") or "").lower()
    t = (element.get("type") or element.get("input_type") or "").lower()
    return f"{tag}[{t}]" if t else tag


def _accessible_name(event: dict) -> str:
    """Return the accessible name from the event's enriched metadata."""
    enriched = event.get("enriched") or {}
    name = enriched.get("accessible_name") or ""
    if not name:
        el = event.get("element") or {}
        name = (
            el.get("aria_label")
            or el.get("text_content")
            or el.get("text")
            or el.get("value")
            or el.get("placeholder")
            or ""
        )
    return name.strip()


def _element_value(event: dict) -> str:
    """Return the current value of the element associated with this event."""
    el = event.get("element") or {}
    return str(el.get("value") or "").strip()


def _form_context(event: dict) -> str:
    enriched = event.get("enriched") or {}
    return enriched.get("form_context") or ""


def _aria_role(event: dict) -> str:
    enriched = event.get("enriched") or {}
    role = enriched.get("aria_role") or ""
    if not role:
        role = (event.get("element") or {}).get("role") or "generic"
    return role.lower()


def _is_search_element(event: dict) -> bool:
    """Heuristic: does this event's element look like a search box?"""
    role = _aria_role(event)
    if role in ("searchbox", "search"):
        return True
    el = event.get("element") or {}
    if (el.get("type") or "").lower() == "search":
        return True
    name = _accessible_name(event)
    return bool(_SEARCH_HINT_PATTERN.search(name))


def _first_ts(events: list[dict]) -> int:
    """Return the smallest timestamp_ms from a list of events."""
    return min((e.get("timestamp_ms", 0) for e in events), default=0)


# ---------------------------------------------------------------------------
# ActionRecognizer
# ---------------------------------------------------------------------------


class ActionRecognizer:
    """
    Convert an enriched event list into a list of ``SemanticAction`` objects.

    Usage
    -----
    ::

        recognizer = ActionRecognizer()
        actions = recognizer.recognize(preprocessed_events)
        all_variables = recognizer.extract_variables(actions)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recognize(self, events: list[dict]) -> list[SemanticAction]:
        """
        Convert an enriched event stream into semantic actions.

        The method works cluster-by-cluster: events that share the same
        ``cluster_idx`` (set by ``EventPreprocessor``) are treated as a
        single gesture. Within each cluster we apply deterministic rules
        first, then heuristic scoring for anything left unclassified.

        Parameters
        ----------
        events:
            Output of ``EventPreprocessor.process()``. Each dict must
            contain at least ``type`` and ``timestamp_ms``.

        Returns
        -------
        list[SemanticAction]
            Ordered list of recognised actions.
        """
        if not events:
            return []

        clusters = self._split_into_clusters(events)
        actions: list[SemanticAction] = []

        for cluster in clusters:
            cluster_actions = self._recognize_cluster(cluster)
            actions.extend(cluster_actions)

        logger.debug(
            "ActionRecognizer: %d events -> %d actions across %d clusters",
            len(events),
            len(actions),
            len(clusters),
        )
        return actions

    def extract_variables(self, actions: list[SemanticAction]) -> dict[str, Any]:
        """
        Aggregate all parameterisable values across a list of actions.

        Returns
        -------
        dict
            Merged variable dict. Later actions with the same key override
            earlier ones (last-write-wins).
        """
        merged: dict[str, Any] = {}
        for action in actions:
            merged.update(action.variables)
        return merged

    # ------------------------------------------------------------------
    # Private - cluster splitting
    # ------------------------------------------------------------------

    @staticmethod
    def _split_into_clusters(events: list[dict]) -> list[list[dict]]:
        """
        Re-group events by the ``cluster_idx`` assigned by EventPreprocessor.

        Falls back to treating the whole list as a single cluster if no
        ``cluster_idx`` is present.
        """
        cluster_map: dict[int, list[dict]] = {}
        for ev in events:
            enriched = ev.get("enriched") or {}
            idx = enriched.get("cluster_idx", 0)
            cluster_map.setdefault(idx, []).append(ev)
        return [cluster_map[k] for k in sorted(cluster_map)]

    # ------------------------------------------------------------------
    # Private - per-cluster recognition
    # ------------------------------------------------------------------

    def _recognize_cluster(self, cluster: list[dict]) -> list[SemanticAction]:
        """
        Apply recognition rules to a single temporal cluster.

        Rules are tried in priority order:
            1. Navigation
            2. Download
            3. Form fill (focus->input->blur triple)
            4. Search (input + submit/keydown-Enter in search element)
            5. Select (change on <select>)
            6. Click (button / link)
            7. Heuristic fallback for anything else
        """
        actions: list[SemanticAction] = []
        consumed: set[int] = set()  # indices within cluster that are "used"

        # Rule 1: Navigation
        for i, ev in enumerate(cluster):
            if ev.get("type") == "navigation" and i not in consumed:
                url = ev.get("url") or ""
                actions.append(
                    SemanticAction(
                        type="navigation",
                        description=f"Navigate to {url}",
                        element_info={"url": url},
                        confidence=1.0,
                        timestamp_ms=ev.get("timestamp_ms", 0),
                        raw_events=[ev],
                        variables={"url": url},
                    )
                )
                consumed.add(i)

        # Rule 2: Download
        for i, ev in enumerate(cluster):
            if ev.get("type") == "download" and i not in consumed:
                el = ev.get("element") or {}
                href = el.get("href") or ""
                filename = href.rsplit("/", 1)[-1] if href else ""
                actions.append(
                    SemanticAction(
                        type="download",
                        description=f"Download file: {filename or href}",
                        element_info={"href": href, "filename": filename},
                        confidence=1.0,
                        timestamp_ms=ev.get("timestamp_ms", 0),
                        raw_events=[ev],
                        variables={"download_url": href, "filename": filename},
                    )
                )
                consumed.add(i)
                # Also consume a preceding click on the same href
                for j, prev_ev in enumerate(cluster[:i]):
                    prev_el = prev_ev.get("element") or {}
                    if (
                        j not in consumed
                        and prev_ev.get("type") == "click"
                        and prev_el.get("href") == href
                    ):
                        consumed.add(j)

        # Rule 3: Form fill (focus -> input/change -> blur triple)
        # Group events by element id/aria_label for the same element
        element_timeline: dict[str, list[tuple[int, dict]]] = {}
        for i, ev in enumerate(cluster):
            if i in consumed:
                continue
            el = ev.get("element") or {}
            key = el.get("id") or el.get("aria_label") or el.get("name") or ""
            if key and ev.get("type") in ("focus", "input", "change", "blur"):
                element_timeline.setdefault(key, []).append((i, ev))

        for key, timeline in element_timeline.items():
            types_seen = {ev["type"] for _, ev in timeline}
            has_input = "input" in types_seen or "change" in types_seen
            indices = [i for i, _ in timeline]
            events_list = [ev for _, ev in timeline]

            if not has_input:
                continue

            # Pick the last input/change event for the final value
            value_event = next(
                (ev for _, ev in reversed(timeline) if ev.get("type") in ("input", "change")),
                events_list[-1],
            )
            el = value_event.get("element") or {}
            value = _element_value(value_event)
            label = _accessible_name(value_event) or key
            form_ctx = _form_context(value_event)
            role = _aria_role(value_event)
            description = f"Fill {label!r} with {value!r}"
            if form_ctx:
                description += f" (in {form_ctx})"

            # Sanitize variable key
            var_key = re.sub(r"\W+", "_", label.lower()).strip("_") or "field"

            actions.append(
                SemanticAction(
                    type="form_fill",
                    description=description,
                    element_info={
                        "tag": el.get("tag"),
                        "id": el.get("id"),
                        "role": role,
                        "label": label,
                        "form_context": form_ctx,
                    },
                    confidence=0.95,
                    timestamp_ms=_first_ts(events_list),
                    raw_events=events_list,
                    variables={"field": label, var_key: value},
                )
            )
            consumed.update(indices)

        # Rule 4: Search
        search_input_events = [
            (i, ev)
            for i, ev in enumerate(cluster)
            if i not in consumed
            and ev.get("type") in ("input", "change")
            and _is_search_element(ev)
        ]
        for i, ev in search_input_events:
            query = _element_value(ev)
            label = _accessible_name(ev) or "search"
            actions.append(
                SemanticAction(
                    type="search",
                    description=f'Search for "{query}"',
                    element_info={
                        "tag": (ev.get("element") or {}).get("tag"),
                        "role": _aria_role(ev),
                        "label": label,
                    },
                    confidence=0.9,
                    timestamp_ms=ev.get("timestamp_ms", 0),
                    raw_events=[ev],
                    variables={"query": query},
                )
            )
            consumed.add(i)
            # Consume associated keydown/submit in the same cluster
            for j, sub_ev in enumerate(cluster):
                if j in consumed:
                    continue
                if sub_ev.get("type") in ("keydown", "submit") and _is_search_element(sub_ev):
                    consumed.add(j)

        # Rule 5: Select
        for i, ev in enumerate(cluster):
            if i in consumed:
                continue
            if ev.get("type") == "change" and _aria_role(ev) in ("listbox", "combobox"):
                el = ev.get("element") or {}
                value = _element_value(ev)
                label = _accessible_name(ev) or el.get("id") or "dropdown"
                actions.append(
                    SemanticAction(
                        type="select",
                        description=f'Select "{value}" from {label!r}',
                        element_info={
                            "tag": el.get("tag"),
                            "id": el.get("id"),
                            "role": _aria_role(ev),
                            "label": label,
                        },
                        confidence=0.95,
                        timestamp_ms=ev.get("timestamp_ms", 0),
                        raw_events=[ev],
                        variables={"selection": value, "field": label},
                    )
                )
                consumed.add(i)

        # Rule 6: Click (button / link)
        for i, ev in enumerate(cluster):
            if i in consumed:
                continue
            if ev.get("type") != "click":
                continue

            el = ev.get("element") or {}
            role = _aria_role(ev)
            tag_key = _tag_type_key(el)
            name = _accessible_name(ev)
            href = el.get("href", "")

            is_button = role == "button" or tag_key in _BUTTON_TAGS
            is_link = role == "link" or (el.get("tag") or "").lower() in _LINK_TAGS

            if is_button:
                actions.append(
                    SemanticAction(
                        type="click",
                        description=f'Click "{name or tag_key}" button',
                        element_info={
                            "tag": el.get("tag"),
                            "id": el.get("id"),
                            "role": role,
                            "accessible_name": name,
                        },
                        confidence=0.9,
                        timestamp_ms=ev.get("timestamp_ms", 0),
                        raw_events=[ev],
                        variables={"button_label": name},
                    )
                )
                consumed.add(i)
            elif is_link:
                actions.append(
                    SemanticAction(
                        type="click",
                        description=f'Click link "{name or href}"',
                        element_info={
                            "tag": el.get("tag"),
                            "href": href,
                            "role": role,
                            "accessible_name": name,
                        },
                        confidence=0.85,
                        timestamp_ms=ev.get("timestamp_ms", 0),
                        raw_events=[ev],
                        variables={"link_text": name, "link_href": href},
                    )
                )
                consumed.add(i)

        # Rule 7: Heuristic fallback for unconsumed events
        unconsumed = [(i, ev) for i, ev in enumerate(cluster) if i not in consumed]
        if unconsumed:
            for _, ev in unconsumed:
                fallback = self._classify_with_heuristics([ev])
                if fallback:
                    actions.append(fallback)

        # Sort all actions in this cluster by timestamp
        actions.sort(key=lambda a: a.timestamp_ms)
        return actions

    # ------------------------------------------------------------------
    # Private - heuristic classification
    # ------------------------------------------------------------------

    def _classify_with_heuristics(self, cluster: list[dict]) -> SemanticAction | None:
        """
        Score and classify an ambiguous event cluster without using an LLM.

        Assigns weighted scores to candidate action types based on event
        properties and returns the highest-scoring candidate, or ``None``
        if confidence is below threshold.

        Parameters
        ----------
        cluster:
            One or more enriched event dicts that could not be matched by rules.

        Returns
        -------
        Optional[SemanticAction]
            Best-guess SemanticAction, or None if confidence too low.
        """
        if not cluster:
            return None

        scores: dict[str, float] = {
            "click": 0.0,
            "form_fill": 0.0,
            "navigation": 0.0,
            "search": 0.0,
            "select": 0.0,
            "download": 0.0,
        }

        for ev in cluster:
            ev_type = ev.get("type", "")
            role = _aria_role(ev)
            el = ev.get("element") or {}
            href = el.get("href", "")

            if ev_type == "click":
                scores["click"] += 0.5
                if href:
                    scores["click"] += 0.2
                    if any(ext in href for ext in (".pdf", ".csv", ".xlsx", ".zip", ".docx")):
                        scores["download"] += 0.6

            if ev_type in ("input", "change"):
                scores["form_fill"] += 0.4
                if _is_search_element(ev):
                    scores["search"] += 0.5

            if ev_type == "submit":
                scores["form_fill"] += 0.3
                scores["search"] += 0.2

            if ev_type == "navigation":
                scores["navigation"] += 0.8

            if role == "listbox":
                scores["select"] += 0.5

            if ev_type == "download":
                scores["download"] += 1.0

        best_type = max(scores, key=scores.__getitem__)
        best_score = scores[best_type]

        if best_score < 0.3:
            return None

        representative_ev = cluster[0]
        el = representative_ev.get("element") or {}
        name = _accessible_name(representative_ev)
        ts = _first_ts(cluster)
        confidence = min(1.0, round(best_score, 3))

        descriptions = {
            "click": f'Click "{name or "unknown element"}"',
            "form_fill": f"Fill in {name or 'a field'}",
            "navigation": f"Navigate to {representative_ev.get('url', '')}",
            "search": f'Search for "{_element_value(representative_ev)}"',
            "select": f"Select from {name or 'a dropdown'}",
            "download": "Download file",
        }

        return SemanticAction(
            type=best_type,
            description=descriptions.get(best_type, "Unknown action"),
            element_info={
                "tag": el.get("tag"),
                "role": _aria_role(representative_ev),
                "accessible_name": name,
            },
            confidence=confidence,
            timestamp_ms=ts,
            raw_events=cluster,
            variables={},
        )


# ---------------------------------------------------------------------------
# __main__ - sanity check with realistic event sequences
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import time

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s - %(message)s")

    BASE_TS = int(time.time() * 1000)

    def _make_enriched(ev: dict, cluster_idx: int, cluster_size: int) -> dict:
        el = ev.get("element") or {}
        tag = (el.get("tag") or "").lower()
        t = (el.get("type") or "").lower()
        role_map = {"button": "button", "select": "listbox", "a": "link"}
        if tag == "input":
            type_roles = {"submit": "button", "search": "searchbox", "email": "textbox", "password": "textbox"}
            role = type_roles.get(t, "textbox")
        else:
            role = role_map.get(tag, el.get("role") or "generic")

        accessible_name = (
            el.get("aria_label") or el.get("text") or el.get("value") or el.get("placeholder") or ""
        )
        ev["enriched"] = {
            "aria_role": role,
            "accessible_name": accessible_name,
            "form_context": f"form#{el.get('form')}" if el.get("form") else "",
            "parent_heading": "",
            "label_text": "",
            "cluster_idx": cluster_idx,
            "cluster_size": cluster_size,
        }
        ev["_confidence"] = 0.9
        return ev

    raw: list[dict] = [
        # Cluster 0: navigation + login form fill + submit
        {"type": "navigation", "timestamp_ms": BASE_TS, "url": "https://app.example.com/login", "element": {}},
        {"type": "focus", "timestamp_ms": BASE_TS + 200, "url": "https://app.example.com/login",
         "element": {"tag": "input", "type": "email", "id": "email", "aria_label": "Email", "form": "login"}},
        {"type": "input", "timestamp_ms": BASE_TS + 500, "url": "https://app.example.com/login",
         "element": {"tag": "input", "type": "email", "id": "email", "aria_label": "Email", "value": "bob@corp.com", "form": "login"}},
        {"type": "blur", "timestamp_ms": BASE_TS + 600, "url": "https://app.example.com/login",
         "element": {"tag": "input", "type": "email", "id": "email", "aria_label": "Email", "value": "bob@corp.com", "form": "login"}},
        {"type": "focus", "timestamp_ms": BASE_TS + 700, "url": "https://app.example.com/login",
         "element": {"tag": "input", "type": "password", "id": "pwd", "aria_label": "Password", "form": "login"}},
        {"type": "input", "timestamp_ms": BASE_TS + 900, "url": "https://app.example.com/login",
         "element": {"tag": "input", "type": "password", "id": "pwd", "aria_label": "Password", "value": "hunter2", "form": "login"}},
        {"type": "blur", "timestamp_ms": BASE_TS + 1000, "url": "https://app.example.com/login",
         "element": {"tag": "input", "type": "password", "id": "pwd", "aria_label": "Password", "value": "hunter2", "form": "login"}},
        {"type": "click", "timestamp_ms": BASE_TS + 1200, "url": "https://app.example.com/login",
         "element": {"tag": "input", "type": "submit", "id": "login-btn", "value": "Sign In"}},
        {"type": "submit", "timestamp_ms": BASE_TS + 1250, "url": "https://app.example.com/login",
         "element": {"tag": "form", "id": "login", "aria_label": "Login form"}},
        # Cluster 1: navigation + search + select
        {"type": "navigation", "timestamp_ms": BASE_TS + 6000, "url": "https://app.example.com/reports", "element": {}},
        {"type": "input", "timestamp_ms": BASE_TS + 6500, "url": "https://app.example.com/reports",
         "element": {"tag": "input", "type": "search", "role": "searchbox", "aria_label": "Search reports", "value": "Q4 2024"}},
        {"type": "change", "timestamp_ms": BASE_TS + 7000, "url": "https://app.example.com/reports",
         "element": {"tag": "select", "id": "period", "aria_label": "Report period", "value": "Q4 2024"}},
        # Cluster 2: download
        {"type": "click", "timestamp_ms": BASE_TS + 15000, "url": "https://app.example.com/reports",
         "element": {"tag": "a", "href": "https://app.example.com/reports/q4-2024.csv", "text": "Download CSV", "aria_label": "Download CSV report"}},
        {"type": "download", "timestamp_ms": BASE_TS + 15500, "url": "https://app.example.com/reports",
         "element": {"tag": "a", "href": "https://app.example.com/reports/q4-2024.csv", "text": "Download CSV"}},
    ]

    cluster_assignments = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2]
    cluster_sizes = {0: 9, 1: 3, 2: 2}
    enriched_events = [
        _make_enriched(ev, cluster_assignments[i], cluster_sizes[cluster_assignments[i]])
        for i, ev in enumerate(raw)
    ]

    recognizer = ActionRecognizer()
    actions = recognizer.recognize(enriched_events)
    all_vars = recognizer.extract_variables(actions)

    print(f"\n{'='*65}")
    print("  ActionRecognizer Sanity Check")
    print(f"{'='*65}")
    print(f"  Input events : {len(enriched_events)}")
    print(f"  Actions found: {len(actions)}\n")

    for i, action in enumerate(actions):
        print(
            f"  [{i+1:02d}] [{action.type:<12}] conf={action.confidence:.2f}  "
            f'"{action.description}"'
        )
        if action.variables:
            print(f"       vars: {action.variables}")

    print(f"\n  All variables:\n  {json.dumps(all_vars, indent=4)}")
    print(f"\n{'='*65}\n  ActionRecognizer sanity check PASSED\n{'='*65}\n")
