"""
Recordings — Event Preprocessor
================================
Layer 1 of the Hierarchical Semantic Action Extraction (HSAE) pipeline.

Responsibilities:
    1. **Noise filtering** — drop low-signal events (scroll, mousemove, etc.)
    2. **Temporal clustering** — group events within a configurable time window
       into logical clusters that correspond to single user actions.
    3. **DOM enrichment** — augment each event's element dict with derived
       semantic metadata: ARIA role, accessible name, form context, nearby
       label text, and parent heading.

Designed to be fully offline (no network calls, no database access).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Event types that carry actionable user intent.
KEEP_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "click",
        "input",
        "change",
        "submit",
        "navigation",
        "download",
        "focus",
        "blur",
        "keydown",
        "keyup",
        "select",
        "dblclick",
        "contextmenu",
        "paste",
    }
)

#: Tags that map directly to an implied ARIA role without additional attrs.
_TAG_ROLE_MAP: dict[str, str] = {
    "a": "link",
    "button": "button",
    "nav": "navigation",
    "main": "main",
    "aside": "complementary",
    "header": "banner",
    "footer": "contentinfo",
    "form": "form",
    "table": "table",
    "tr": "row",
    "th": "columnheader",
    "td": "cell",
    "ul": "list",
    "ol": "list",
    "li": "listitem",
    "select": "listbox",
    "textarea": "textbox",
    "dialog": "dialog",
    "article": "article",
    "section": "region",
    "img": "img",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
    "fieldset": "group",
    "legend": "group",
    "details": "group",
    "summary": "button",
    "search": "search",
    "checkbox": "checkbox",
    "radio": "radio",
}

#: input[type] -> ARIA role mapping.
_INPUT_TYPE_ROLE_MAP: dict[str, str] = {
    "submit": "button",
    "button": "button",
    "reset": "button",
    "checkbox": "checkbox",
    "radio": "radio",
    "range": "slider",
    "search": "searchbox",
    "text": "textbox",
    "email": "textbox",
    "password": "textbox",
    "number": "spinbutton",
    "tel": "textbox",
    "url": "textbox",
    "date": "textbox",
    "datetime-local": "textbox",
    "time": "textbox",
    "month": "textbox",
    "week": "textbox",
    "color": "textbox",
    "file": "textbox",
    "hidden": "none",
}


# ---------------------------------------------------------------------------
# EventPreprocessor
# ---------------------------------------------------------------------------


class EventPreprocessor:
    """
    Cleans and enriches raw browser event streams for downstream processing.

    Parameters
    ----------
    cluster_window_ms:
        Events within this many milliseconds of each other are grouped into
        the same temporal cluster (one logical user gesture).
    min_confidence:
        Minimum confidence threshold below which an enriched event is dropped.
        Currently used as a guard against events with no element information
        and no usable URL.
    """

    def __init__(
        self,
        cluster_window_ms: int = 2000,
        min_confidence: float = 0.3,
    ) -> None:
        self.cluster_window_ms = cluster_window_ms
        self.min_confidence = min_confidence

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, events: list[dict]) -> list[dict]:
        """
        Transform a raw browser event list into a cleaned, enriched list.

        Pipeline stages:
            1. Filter noise events.
            2. Sort chronologically.
            3. Cluster temporally.
            4. Enrich each event with semantic DOM metadata.
            5. Filter low-confidence results.

        Parameters
        ----------
        events:
            Raw browser events. Each dict must contain at minimum:
            ``type`` (str), ``timestamp_ms`` (int), ``element`` (dict|None),
            ``url`` (str|None).

        Returns
        -------
        list[dict]
            Enriched, filtered event dicts ready for ``ActionRecognizer``.
        """
        if not events:
            return []

        # Stage 1 - filter noise
        filtered = [e for e in events if self._is_actionable(e)]
        logger.debug(
            "Preprocessor: %d/%d events kept after noise filter",
            len(filtered), len(events),
        )

        if not filtered:
            return []

        # Stage 2 - chronological sort
        filtered.sort(key=lambda e: e.get("timestamp_ms", 0))

        # Stage 3 - temporal clustering
        clusters = self._cluster_events(filtered)
        logger.debug("Preprocessor: formed %d temporal clusters", len(clusters))

        # Stage 4 - enrich + flatten
        enriched: list[dict] = []
        for cluster_idx, cluster in enumerate(clusters):
            # Provide the full cluster as "page_elements" context for form detection
            for event in cluster:
                enriched_event = self._enrich_event(event, cluster, cluster_idx)
                enriched.append(enriched_event)

        # Stage 5 - confidence filter
        result = [e for e in enriched if e.get("_confidence", 1.0) >= self.min_confidence]
        logger.debug("Preprocessor: %d events after confidence filter", len(result))
        return result

    # ------------------------------------------------------------------
    # Private - noise filtering
    # ------------------------------------------------------------------

    @staticmethod
    def _is_actionable(event: dict) -> bool:
        """Return True if the event type carries actionable user intent."""
        return event.get("type", "").lower() in KEEP_EVENT_TYPES

    # ------------------------------------------------------------------
    # Private - temporal clustering
    # ------------------------------------------------------------------

    def _cluster_events(self, events: list[dict]) -> list[list[dict]]:
        """
        Group sorted events into temporal clusters.

        Two consecutive events belong to the same cluster when the gap
        between their ``timestamp_ms`` values is less than
        ``self.cluster_window_ms``.

        Returns
        -------
        list[list[dict]]
            Ordered list of clusters, each containing 1 or more event dicts.
        """
        if not events:
            return []

        clusters: list[list[dict]] = []
        current_cluster: list[dict] = [events[0]]

        for event in events[1:]:
            prev_ts = current_cluster[-1].get("timestamp_ms", 0)
            curr_ts = event.get("timestamp_ms", 0)
            if (curr_ts - prev_ts) <= self.cluster_window_ms:
                current_cluster.append(event)
            else:
                clusters.append(current_cluster)
                current_cluster = [event]

        clusters.append(current_cluster)
        return clusters

    # ------------------------------------------------------------------
    # Private - DOM enrichment
    # ------------------------------------------------------------------

    def _enrich_event(
        self,
        event: dict,
        cluster: list[dict],
        cluster_idx: int,
    ) -> dict:
        """
        Add semantic metadata to a single event dict.

        Adds the following keys under ``enriched``:
        - ``aria_role``
        - ``accessible_name``
        - ``form_context``
        - ``parent_heading``
        - ``label_text``
        - ``cluster_idx``
        - ``cluster_size``

        Also sets ``_confidence`` on the event.
        """
        element: dict = event.get("element") or {}

        aria_role = self._get_aria_role(element)
        accessible_name = self._get_accessible_name(element)
        form_context = self._get_form_context(element, cluster)
        parent_heading = element.get("parent_heading") or element.get("section_heading", "")
        label_text = element.get("label") or element.get("nearby_label", "")

        enriched = dict(event)  # shallow copy
        enriched["enriched"] = {
            "aria_role": aria_role,
            "accessible_name": accessible_name,
            "form_context": form_context,
            "parent_heading": parent_heading,
            "label_text": label_text,
            "cluster_idx": cluster_idx,
            "cluster_size": len(cluster),
        }

        # Compute a simple confidence score
        confidence = self._compute_confidence(event, aria_role, accessible_name)
        enriched["_confidence"] = confidence

        return enriched

    def _compute_confidence(
        self,
        event: dict,
        aria_role: str,
        accessible_name: str,
    ) -> float:
        """
        Heuristic confidence score in [0, 1].

        Deducts points for missing element info and unknown roles.
        """
        score = 1.0
        element: dict = event.get("element") or {}

        if not element:
            score -= 0.4  # No element info at all
        if not accessible_name:
            score -= 0.15
        if aria_role == "generic":
            score -= 0.1
        if not event.get("url"):
            score -= 0.05

        # Bonus for high-signal event types
        if event.get("type") in ("submit", "navigation", "download"):
            score = min(1.0, score + 0.1)

        return max(0.0, round(score, 3))

    # ------------------------------------------------------------------
    # Private - ARIA role inference
    # ------------------------------------------------------------------

    @staticmethod
    def _get_aria_role(element: dict) -> str:
        """
        Infer the ARIA role for an element.

        Priority:
            1. Explicit ``role`` attribute on the element dict.
            2. ``input[type]`` -> role mapping.
            3. HTML tag -> default implicit role.
            4. ``"generic"`` fallback.

        Parameters
        ----------
        element:
            Dict with keys like ``tag``, ``type``, ``role``, ``aria_label``, etc.

        Returns
        -------
        str
            ARIA role string (e.g. ``"button"``, ``"textbox"``, ``"listbox"``).
        """
        # 1. Explicit role attribute wins
        if element.get("role"):
            return element["role"].lower().strip()

        tag = (element.get("tag") or "").lower().strip()

        # 2. Special-case <input> - role depends on type attribute
        if tag == "input":
            input_type = (element.get("type") or element.get("input_type") or "text").lower()
            return _INPUT_TYPE_ROLE_MAP.get(input_type, "textbox")

        # 3. Implicit role from tag
        if tag in _TAG_ROLE_MAP:
            return _TAG_ROLE_MAP[tag]

        # 4. Fallback
        return "generic"

    # ------------------------------------------------------------------
    # Private - accessible name computation
    # ------------------------------------------------------------------

    @staticmethod
    def _get_accessible_name(element: dict) -> str:
        """
        Compute the accessible name of an element using the ARIA spec priority.

        Priority (first non-empty wins):
            1. ``aria_label`` attribute
            2. ``title`` attribute
            3. ``value`` attribute (for inputs)
            4. ``text_content`` / ``text`` (inner text)
            5. ``placeholder``
            6. ``alt`` (images)
            7. ``href`` last path segment (links with no text)

        Parameters
        ----------
        element:
            Raw element dict from the browser event.

        Returns
        -------
        str
            The accessible name, or empty string if none could be derived.
        """
        candidates: list[str | None] = [
            element.get("aria_label"),
            element.get("title"),
            element.get("value"),
            element.get("text_content"),
            element.get("text"),
            element.get("placeholder"),
            element.get("alt"),
        ]

        for candidate in candidates:
            if candidate and str(candidate).strip():
                return str(candidate).strip()

        # Last resort for links: extract the final path segment from href
        href = element.get("href", "")
        if href:
            segment = href.rstrip("/").rsplit("/", 1)[-1]
            if segment and not segment.startswith("http"):
                return segment

        return ""

    # ------------------------------------------------------------------
    # Private - form context detection
    # ------------------------------------------------------------------

    @staticmethod
    def _get_form_context(element: dict, page_elements: list[dict]) -> str:
        """
        Determine which form or fieldset the element belongs to.

        This is a best-effort heuristic using the element's own attributes
        and the surrounding cluster of events (as a proxy for co-located
        DOM siblings).

        Priority:
            1. Element's own ``form`` attribute (HTML ``form`` attr pointing to a form id).
            2. Element's ``fieldset`` attribute.
            3. Search ``page_elements`` for the closest preceding ``submit`` event
               that shares the same base URL - infer they are in the same form.
            4. Fallback to empty string.

        Parameters
        ----------
        element:
            The element dict for which to find form context.
        page_elements:
            Other events in the same temporal cluster (used as siblings).

        Returns
        -------
        str
            A descriptive form context string, e.g. ``"form#login-form"``
            or ``"fieldset: Billing Address"``.
        """
        # 1. Explicit HTML form attribute
        form_attr = element.get("form") or element.get("form_id")
        if form_attr:
            return f"form#{form_attr}"

        # 2. Explicit fieldset
        fieldset = element.get("fieldset") or element.get("fieldset_legend")
        if fieldset:
            return f"fieldset: {fieldset}"

        # 3. Look for submit events in the same cluster
        for sibling_event in page_elements:
            sibling_el = sibling_event.get("element") or {}
            if sibling_event.get("type") == "submit":
                form_id = sibling_el.get("id") or sibling_el.get("form_id")
                if form_id:
                    return f"form#{form_id}"
                form_name = sibling_el.get("aria_label") or sibling_el.get("text", "")
                if form_name:
                    return f"form: {form_name}"
                return "form: (unnamed)"

        # 4. Look for a form element type in the cluster
        for sibling_event in page_elements:
            sibling_el = sibling_event.get("element") or {}
            if (sibling_el.get("tag") or "").lower() == "form":
                name = sibling_el.get("id") or sibling_el.get("name") or sibling_el.get("aria_label", "")
                return f"form#{name}" if name else "form: (unnamed)"

        return ""


# ---------------------------------------------------------------------------
# __main__ - sanity check with 20 synthetic events
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import time

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s - %(message)s")

    BASE_TS = int(time.time() * 1000)  # now in ms

    raw_events: list[dict] = [
        # 0 - navigation (keep)
        {"type": "navigation", "timestamp_ms": BASE_TS, "url": "https://example.com/login", "element": {}},
        # 1 - mousemove (noise - drop)
        {"type": "mousemove", "timestamp_ms": BASE_TS + 50, "url": "https://example.com/login", "element": {"tag": "body"}},
        # 2 - scroll (noise - drop)
        {"type": "scroll", "timestamp_ms": BASE_TS + 100, "url": "https://example.com/login", "element": {}},
        # 3 - focus on email input (keep)
        {"type": "focus", "timestamp_ms": BASE_TS + 500, "url": "https://example.com/login",
         "element": {"tag": "input", "type": "email", "id": "email", "aria_label": "Email address", "placeholder": "user@example.com"}},
        # 4 - input on email (keep)
        {"type": "input", "timestamp_ms": BASE_TS + 800, "url": "https://example.com/login",
         "element": {"tag": "input", "type": "email", "id": "email", "aria_label": "Email address", "value": "alice@corp.com", "form": "login-form"}},
        # 5 - blur on email (keep)
        {"type": "blur", "timestamp_ms": BASE_TS + 900, "url": "https://example.com/login",
         "element": {"tag": "input", "type": "email", "id": "email", "aria_label": "Email address", "value": "alice@corp.com", "form": "login-form"}},
        # 6 - focus on password (keep)
        {"type": "focus", "timestamp_ms": BASE_TS + 1100, "url": "https://example.com/login",
         "element": {"tag": "input", "type": "password", "id": "password", "aria_label": "Password", "form": "login-form"}},
        # 7 - input on password (keep)
        {"type": "input", "timestamp_ms": BASE_TS + 1300, "url": "https://example.com/login",
         "element": {"tag": "input", "type": "password", "id": "password", "aria_label": "Password", "value": "s3cr3t!", "form": "login-form"}},
        # 8 - blur on password (keep)
        {"type": "blur", "timestamp_ms": BASE_TS + 1400, "url": "https://example.com/login",
         "element": {"tag": "input", "type": "password", "id": "password", "aria_label": "Password", "value": "s3cr3t!", "form": "login-form"}},
        # 9 - click submit button (keep)
        {"type": "click", "timestamp_ms": BASE_TS + 1800, "url": "https://example.com/login",
         "element": {"tag": "input", "type": "submit", "id": "login-btn", "value": "Sign In", "form": "login-form"}},
        # 10 - submit (keep)
        {"type": "submit", "timestamp_ms": BASE_TS + 1850, "url": "https://example.com/login",
         "element": {"tag": "form", "id": "login-form"}},
        # 11 - navigation after login (keep) - 3s gap -> new cluster
        {"type": "navigation", "timestamp_ms": BASE_TS + 5000, "url": "https://example.com/dashboard", "element": {}},
        # 12 - mouseover (noise - drop)
        {"type": "mouseover", "timestamp_ms": BASE_TS + 5200, "url": "https://example.com/dashboard", "element": {"tag": "nav"}},
        # 13 - click a nav link (keep)
        {"type": "click", "timestamp_ms": BASE_TS + 6000, "url": "https://example.com/dashboard",
         "element": {"tag": "a", "href": "https://example.com/reports", "text": "Reports", "aria_label": "Go to Reports"}},
        # 14 - navigation (keep) - 1s after click -> same cluster
        {"type": "navigation", "timestamp_ms": BASE_TS + 6800, "url": "https://example.com/reports", "element": {}},
        # 15 - change on select dropdown (keep)
        {"type": "change", "timestamp_ms": BASE_TS + 8000, "url": "https://example.com/reports",
         "element": {"tag": "select", "id": "report-type", "aria_label": "Report type", "value": "Monthly"}},
        # 16 - input in search box (keep)
        {"type": "input", "timestamp_ms": BASE_TS + 9000, "url": "https://example.com/reports",
         "element": {"tag": "input", "type": "search", "role": "searchbox", "aria_label": "Search reports", "value": "Q4 2024"}},
        # 17 - keydown Enter to submit search (keep)
        {"type": "keydown", "timestamp_ms": BASE_TS + 9200, "url": "https://example.com/reports",
         "element": {"tag": "input", "type": "search", "role": "searchbox", "aria_label": "Search reports", "value": "Q4 2024"}},
        # 18 - click download link (keep) - new cluster (7s gap)
        {"type": "click", "timestamp_ms": BASE_TS + 16000, "url": "https://example.com/reports",
         "element": {"tag": "a", "href": "https://example.com/reports/download/q4-2024.csv", "text": "Download CSV", "title": "Download Q4 2024 report"}},
        # 19 - download event (keep)
        {"type": "download", "timestamp_ms": BASE_TS + 16500, "url": "https://example.com/reports",
         "element": {"tag": "a", "href": "https://example.com/reports/download/q4-2024.csv", "text": "Download CSV"}},
    ]

    preprocessor = EventPreprocessor(cluster_window_ms=2000, min_confidence=0.3)
    result = preprocessor.process(raw_events)

    print(f"\n{'='*60}")
    print("  EventPreprocessor Sanity Check")
    print(f"{'='*60}")
    print(f"  Raw events      : {len(raw_events)}")
    print(f"  Enriched events : {len(result)}")
    print()

    for i, ev in enumerate(result):
        enr = ev.get("enriched", {})
        print(
            f"  [{i:02d}] type={ev['type']:<12} "
            f"cluster={enr.get('cluster_idx')}/{enr.get('cluster_size')-1}  "
            f"role={enr.get('aria_role'):<12} "
            f"name='{enr.get('accessible_name')}'  "
            f"form='{enr.get('form_context')}'  "
            f"conf={ev.get('_confidence')}"
        )

    print()
    print("  Sample enriched event (email input):")
    matching = [e for e in result if e.get("type") == "input"
                and "email" in str((e.get("element") or {}).get("aria_label", "")).lower()]
    if matching:
        print(json.dumps(matching[0], indent=4, default=str))

    print(f"\n{'='*60}\n  EventPreprocessor sanity check PASSED\n{'='*60}\n")
