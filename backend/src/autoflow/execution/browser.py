"""
Browser Session — Playwright-backed execution of browser workflow steps.

One session (one browser page) lives for the duration of a workflow run, so
navigate → input → click steps act on the same page. Elements are located
semantically (label, role name, placeholder, text) before falling back to CSS,
mirroring how the recorder identifies them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autoflow.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT_MS = 10_000


class ElementNotFoundError(LookupError):
    """No locator strategy matched an element on the page."""


class BrowserSession:
    """Lazily launches Chromium on first use; ``page`` can be injected for tests."""

    def __init__(self, page: Any = None, headless: bool = True, download_dir: str | None = None) -> None:
        self._page = page
        self._headless = headless
        self._download_dir = Path(download_dir or "/tmp/autoflow-downloads")
        self._playwright: Any = None
        self._browser: Any = None

    async def page(self) -> Any:
        if self._page is None:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
            context = await self._browser.new_context(accept_downloads=True)
            self._page = await context.new_page()
            self._page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        return self._page

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._browser = self._playwright = None

    # ─── Element location ────────────────────────────────────────────────────

    async def locate(self, config: dict[str, Any]) -> Any:
        """Return the first locator strategy that matches exactly one or more elements."""
        page = await self.page()
        candidates: list[tuple[str, Any]] = []
        if config.get("selector"):
            candidates.append(("selector", page.locator(config["selector"])))
        if config.get("aria_label"):
            label = config["aria_label"]
            candidates.append(("label", page.get_by_label(label, exact=True)))
            role = config.get("role")
            if role:
                candidates.append(("role", page.get_by_role(role, name=label)))
        if config.get("placeholder"):
            candidates.append(("placeholder", page.get_by_placeholder(config["placeholder"])))
        if config.get("text"):
            candidates.append(("text", page.get_by_text(config["text"], exact=True)))

        for strategy, locator in candidates:
            if await locator.count() > 0:
                logger.debug("Element located", strategy=strategy)
                return locator.first
        tried = ", ".join(s for s, _ in candidates) or "none (no selector/aria_label/placeholder/text)"
        raise ElementNotFoundError(f"No element matched; strategies tried: {tried}")

    # ─── Actions ─────────────────────────────────────────────────────────────

    async def navigate(self, url: str) -> dict[str, Any]:
        page = await self.page()
        await page.goto(url, wait_until="load")
        return {"current_url": page.url}

    async def click(self, config: dict[str, Any]) -> dict[str, Any]:
        await (await self.locate(config)).click()
        return {"clicked": True}

    async def fill(self, config: dict[str, Any]) -> dict[str, Any]:
        value = str(config.get("value", ""))
        await (await self.locate(config)).fill(value)
        return {"value_length": len(value)}

    async def extract(self, config: dict[str, Any]) -> dict[str, Any]:
        text = await (await self.locate(config)).inner_text()
        return {config.get("output_variable", "extracted_value"): text.strip()}

    async def download(self, config: dict[str, Any]) -> dict[str, Any]:
        page = await self.page()
        locator = await self.locate(config)
        async with page.expect_download() as info:
            await locator.click()
        download = await info.value
        self._download_dir.mkdir(parents=True, exist_ok=True)
        target = self._download_dir / download.suggested_filename
        await download.save_as(str(target))
        return {"downloaded_file": str(target)}
