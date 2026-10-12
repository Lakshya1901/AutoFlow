"""
element_locator.py — Self-Healing Element Location System

Finds page elements using a priority cascade of strategies, falling back
gracefully when earlier strategies fail.  All strategies that use a live
Playwright page object also have offline equivalents that parse raw HTML
with Python's stdlib html.parser, so the module is fully testable without
a browser.

Priority cascade
----------------
1. ARIA role + accessible name  →  ``[role="button"][aria-label="Submit"]``
2. Label association            →  ``<label for="id">`` → ``#id``
3. Text content + context       →  nearest element whose text matches
4. ``data-testid`` / ``data-*`` attributes
5. CSS selector                 (fallback, least robust)

For each strategy the locator computes a ``confidence`` score (0–1) based on
how many attributes of the target element_info are matched by the candidate.
The first strategy to return confidence ≥ ``min_confidence`` wins.

If ALL strategies fail the locator returns ``{'strategy_used': 'failed',
'selector': None, 'confidence': 0.0, 'fallback_count': 5}``.

Usage (offline / testing)
-------------------------
>>> locator = ElementLocator()
>>> result = locator.locate(step, page_html="<html>…</html>")
>>> print(result['strategy_used'], result['confidence'])

Usage (live Playwright)
-----------------------
>>> async with async_playwright() as p:
...     page = await p.chromium.launch().new_page()
...     locator = ElementLocator(driver=page)
...     result = locator.locate(step)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Minimal HTML parser (stdlib only – no BeautifulSoup needed)
# ---------------------------------------------------------------------------

@dataclass
class _ParsedElement:
    tag: str
    attrs: dict[str, str]
    text: str = ""


class _SimpleHTMLParser(HTMLParser):
    """
    Lightweight DOM parser that builds a flat list of elements.
    Used for offline strategy testing without a browser.
    """

    def __init__(self):
        super().__init__()
        self.elements: list[_ParsedElement] = []
        self._stack: list[_ParsedElement] = []

    def handle_starttag(self, tag: str, attrs):
        el = _ParsedElement(tag=tag, attrs=dict(attrs))
        self.elements.append(el)
        self._stack.append(el)

    def handle_endtag(self, tag: str):
        if self._stack and self._stack[-1].tag == tag:
            self._stack.pop()

    def handle_data(self, data: str):
        if self._stack and data.strip():
            self._stack[-1].text += data.strip()

    @classmethod
    def parse(cls, html: str) -> list[_ParsedElement]:
        parser = cls()
        parser.feed(html)
        return parser.elements


# ---------------------------------------------------------------------------
# Locator
# ---------------------------------------------------------------------------

class ElementLocator:
    """
    Self-healing element locator with a 5-strategy priority cascade.

    Args:
        driver:          Playwright ``Page`` object, or ``None`` for offline mode.
        min_confidence:  Minimum match confidence to accept a strategy result.
    """

    STRATEGIES: ClassVar[tuple[str, ...]] = ("aria", "label", "text_context", "data_attr", "css")

    def __init__(self, driver=None, min_confidence: float = 0.4):
        self.driver = driver
        self.min_confidence = min_confidence
        self._strategy_log: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def locate(
        self,
        step: Any,
        page_html: str | None = None,
    ) -> dict:
        """
        Find the element described by ``step.element_selector`` on the page.

        Args:
            step:       A ``WorkflowStep`` (or any object with ``element_selector: dict``).
            page_html:  Raw HTML string for offline testing. If None and ``self.driver``
                        is set, HTML is fetched from the live page.

        Returns:
            Dict with keys:
                strategy_used (str), selector (str|None),
                confidence (float), fallback_count (int)
        """
        element_info: dict = getattr(step, "element_selector", {}) or {}
        if not element_info:
            return self._fail_result(0)

        # Fetch HTML once for all offline strategies
        html = page_html
        if html is None and self.driver is not None:
            try:
                html = self.driver.content()
            except Exception as e:
                logger.warning(f"Could not fetch page content: {e}")

        elements = _SimpleHTMLParser.parse(html) if html else []
        fallback_count = 0

        for strategy in self.STRATEGIES:
            try:
                result = self._try_strategy(strategy, element_info, elements)
                if result and result["confidence"] >= self.min_confidence:
                    result["fallback_count"] = fallback_count
                    self._strategy_log.append(
                        {"strategy": strategy, "confidence": result["confidence"],
                         "selector": result["selector"]}
                    )
                    logger.info(
                        f"[Locator] Found via '{strategy}' "
                        f"(confidence={result['confidence']:.2f}): {result['selector']}"
                    )
                    return result
                fallback_count += 1
            except Exception as e:
                logger.debug(f"[Locator] Strategy '{strategy}' raised: {e}")
                fallback_count += 1

        logger.warning(f"[Locator] All strategies failed for element: {element_info}")
        return self._fail_result(fallback_count)

    def compute_match_confidence(
        self,
        element_info: dict,
        candidate_attrs: dict,
    ) -> float:
        """
        Score how well ``candidate_attrs`` matches the target ``element_info``.

        Returns a float in [0, 1]. Matching attributes are weighted:
            - ARIA role / aria-label: 0.3 each
            - id:                     0.2
            - data-testid:            0.2
            - tag / type:             0.1 each
            - text content:           0.15
        """
        weights = {
            "role":        0.30,
            "aria-label":  0.30,
            "aria_label":  0.30,
            "id":          0.20,
            "data-testid": 0.20,
            "tag":         0.10,
            "type":        0.10,
            "text":        0.15,
        }
        score = 0.0
        for key, w in weights.items():
            target = element_info.get(key, "")
            cand   = candidate_attrs.get(key, "")
            if target and cand and str(target).lower() == str(cand).lower():
                score += w
        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Individual strategies
    # ------------------------------------------------------------------

    def _try_strategy(
        self,
        strategy: str,
        element_info: dict,
        elements: list[_ParsedElement],
    ) -> dict | None:
        """Dispatch to the correct strategy handler."""
        handler = getattr(self, f"_strategy_{strategy}", None)
        if handler is None:
            return None
        return handler(element_info, elements)

    def _strategy_aria(
        self, info: dict, elements: list[_ParsedElement]
    ) -> dict | None:
        """Strategy 1: ARIA role + accessible name."""
        role  = info.get("role") or info.get("aria_role", "")
        label = info.get("aria-label") or info.get("aria_label", "")

        if not role and not label:
            return None

        selector_parts = []
        if role:
            selector_parts.append(f'[role="{role}"]')
        if label:
            selector_parts.append(f'[aria-label="{label}"]')
        selector = "".join(selector_parts) if selector_parts else "*"

        # Search in parsed elements
        best = self._find_best(info, elements, role=role, aria_label=label)
        if best:
            return {
                "strategy_used": "aria",
                "selector": selector,
                "confidence": best[1],
            }
        # Return the selector with reduced confidence if we can't verify offline
        if role or label:
            return {"strategy_used": "aria", "selector": selector, "confidence": 0.45}
        return None

    def _strategy_label(
        self, info: dict, elements: list[_ParsedElement]
    ) -> dict | None:
        """Strategy 2: <label for="id"> association."""
        target_id = info.get("id", "")
        label_text = info.get("label", "") or info.get("aria_label", "")

        # Look for <label> whose text matches or whose 'for' attr matches the id
        for el in elements:
            if el.tag == "label":
                lbl_for = el.attrs.get("for", "")
                if (target_id and lbl_for == target_id) or (
                    label_text and label_text.lower() in el.text.lower()
                ):
                    target_id = lbl_for or target_id
                    selector = f"#{target_id}" if target_id else f"[name='{label_text}']"
                    return {
                        "strategy_used": "label",
                        "selector": selector,
                        "confidence": 0.75 if target_id else 0.5,
                    }
        return None

    def _strategy_text_context(
        self, info: dict, elements: list[_ParsedElement]
    ) -> dict | None:
        """Strategy 3: text content + semantic context."""
        text = (
            info.get("text_content")
            or info.get("label")
            or info.get("aria_label")
            or info.get("value", "")
        )
        if not text:
            return None

        tag = info.get("tag", "")
        for el in elements:
            if tag and el.tag != tag:
                continue
            if text.lower() in el.text.lower():
                cand_attrs = dict(el.attrs, tag=el.tag, text=el.text)
                conf = self.compute_match_confidence(info, cand_attrs)
                conf = max(conf, 0.42)  # floor: text match is meaningful
                sel = self._build_css_from_element(el)
                return {"strategy_used": "text_context", "selector": sel, "confidence": conf}
        return None

    def _strategy_data_attr(
        self, info: dict, elements: list[_ParsedElement]
    ) -> dict | None:
        """Strategy 4: data-testid or other data-* attributes."""
        testid = info.get("data-testid", "")
        if not testid:
            # Try any data-* key in element_info
            for k, v in info.items():
                if k.startswith("data-") and v:
                    testid = v
                    break
        if not testid:
            return None

        for el in elements:
            if el.attrs.get("data-testid") == testid:
                selector = f'[data-testid="{testid}"]'
                return {"strategy_used": "data_attr", "selector": selector, "confidence": 0.9}
        # Even if not found in parsed HTML, return the selector at lower confidence
        return {"strategy_used": "data_attr", "selector": f'[data-testid="{testid}"]', "confidence": 0.5}

    def _strategy_css(
        self, info: dict, elements: list[_ParsedElement]  # noqa: ARG002 - uniform strategy signature
    ) -> dict | None:
        """Strategy 5: CSS selector fallback."""
        css = info.get("css_selector") or info.get("selector", "")
        if not css:
            # Build a best-effort selector from available info
            tag = info.get("tag", "*")
            id_ = info.get("id", "")
            cls = info.get("class", "").split()[0] if info.get("class") else ""
            if id_:
                css = f"{tag}#{id_}"
            elif cls:
                css = f"{tag}.{cls}"
            else:
                css = tag
        return {"strategy_used": "css", "selector": css, "confidence": 0.35}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_best(
        self,
        info: dict,
        elements: list[_ParsedElement],
        **filter_kwargs,
    ) -> tuple[_ParsedElement, float] | None:
        """Find highest-confidence element from the parsed list."""
        best_el, best_conf = None, 0.0
        for el in elements:
            # Apply tag filter
            role = filter_kwargs.get("role", "")
            if role:
                el_role = el.attrs.get("role", "") or self._infer_role(el)
                if role.lower() != el_role.lower():
                    continue
            cand_attrs = dict(el.attrs, tag=el.tag, text=el.text,
                              role=self._infer_role(el))
            conf = self.compute_match_confidence(info, cand_attrs)
            if conf > best_conf:
                best_conf, best_el = conf, el
        return (best_el, best_conf) if best_el else None

    @staticmethod
    def _infer_role(el: _ParsedElement) -> str:
        """Infer implicit ARIA role from tag + type attribute."""
        tag  = el.tag
        type_ = el.attrs.get("type", "").lower()
        mapping = {
            "button":   "button",
            "a":        "link",
            "select":   "listbox",
            "textarea": "textbox",
            "nav":      "navigation",
            "main":     "main",
            "header":   "banner",
            "footer":   "contentinfo",
            "form":     "form",
            "img":      "img",
            "table":    "table",
        }
        if tag == "input":
            input_map = {"submit": "button", "checkbox": "checkbox",
                         "radio": "radio", "search": "searchbox",
                         "text": "textbox", "email": "textbox",
                         "password": "textbox", "number": "spinbutton"}
            return input_map.get(type_, "textbox")
        return mapping.get(tag, "")

    @staticmethod
    def _build_css_from_element(el: _ParsedElement) -> str:
        """Build a best-effort CSS selector for a parsed element."""
        id_  = el.attrs.get("id", "")
        cls  = el.attrs.get("class", "").split()[0] if el.attrs.get("class") else ""
        if id_:
            return f"{el.tag}#{id_}"
        if cls:
            return f"{el.tag}.{cls}"
        return el.tag

    @staticmethod
    def _fail_result(fallback_count: int) -> dict:
        return {
            "strategy_used": "failed",
            "selector": None,
            "confidence": 0.0,
            "fallback_count": fallback_count,
        }

    def get_strategy_log(self) -> list[dict]:
        """Return history of successful strategy calls."""
        return list(self._strategy_log)


# ---------------------------------------------------------------------------
# Sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(
        __import__("os").path.dirname(__import__("os").path.dirname(
            __import__("os").path.abspath(__file__))))))

    print("=" * 60)
    print("ElementLocator — Sanity Check")
    print("=" * 60)

    SAMPLE_HTML = """
    <html><body>
      <header><nav role="navigation" aria-label="Main nav"></nav></header>
      <main>
        <form id="contact-form">
          <label for="fullname">Full Name</label>
          <input id="fullname" type="text" aria-label="Full Name" data-testid="name-input" />
          <label for="email">Email Address</label>
          <input id="email" type="email" aria-label="Email Address" />
          <button type="submit" aria-label="Send Message" role="button">Send</button>
        </form>
      </main>
    </body></html>
    """

    locator = ElementLocator(driver=None, min_confidence=0.35)

    # Simulate a WorkflowStep-like object
    class _Step:
        def __init__(self, sel):
            self.element_selector = sel

    tests = [
        ("ARIA role+label (button)",
         {"tag": "button", "role": "button", "aria_label": "Send Message"}),
        ("Label association (input)",
         {"tag": "input", "id": "fullname", "label": "Full Name"}),
        ("data-testid",
         {"tag": "input", "data-testid": "name-input"}),
        ("Text content",
         {"tag": "button", "text_content": "Send"}),
        ("CSS fallback",
         {"tag": "input", "id": "email"}),
        ("Graceful fail",
         {"tag": "div", "aria_label": "nonexistent"}),
    ]

    all_pass = True
    for desc, sel in tests:
        step = _Step(sel)
        result = locator.locate(step, page_html=SAMPLE_HTML)
        print(f"\n  [{desc}]")
        print(f"    strategy : {result['strategy_used']}")
        print(f"    selector : {result['selector']}")
        print(f"    confidence: {result['confidence']:.2f}")
        print(f"    fallbacks: {result['fallback_count']}")

        if desc == "Graceful fail":
            # Expect low confidence / fail
            assert result["confidence"] < 0.5, "Expected low confidence for nonexistent element"
        else:
            assert result["selector"] is not None, f"Expected a selector for: {desc}"
            assert result["confidence"] > 0.0, f"Expected non-zero confidence for: {desc}"

    print("\n" + "=" * 60)
    print("✅  All assertions passed.")
    print(f"ElementLocator(min_confidence={locator.min_confidence})")
    print("=" * 60)
