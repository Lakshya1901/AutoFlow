"""
Integration — replay a workflow in a real headless Chromium

Skipped automatically when Playwright's browser isn't installed
(`python -m playwright install chromium`).
"""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_engine import _make_run

from autoflow.execution.browser import BrowserSession
from autoflow.workflows.engine import StepExecutor, WorkflowEngine
from autoflow.workflows.models import StepType, WorkflowRunStatus

LOGIN_PAGE = """<!doctype html>
<html><body>
  <form onsubmit="event.preventDefault();
        document.getElementById('total').textContent =
          'Welcome ' + document.getElementById('email').value;">
    <label for="email">Email</label><input id="email" type="email">
    <button type="submit">Sign in</button>
  </form>
  <p id="total">signed out</p>
</body></html>"""


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not installed")


@pytest.fixture
def site(tmp_path: Path) -> Iterator[str]:
    (tmp_path / "login.html").write_text(LOGIN_PAGE)
    handler = lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path))  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.mark.asyncio
async def test_workflow_replays_in_real_chromium(db: AsyncSession, site: str) -> None:
    workflow, run = await _make_run(db, [
        {"step_type": StepType.BROWSER_NAVIGATE, "config": {"url": f"{site}/login.html"}},
        {"step_type": StepType.BROWSER_INPUT, "config": {"aria_label": "Email", "value": "{{variables.email}}"}},
        {"step_type": StepType.BROWSER_CLICK, "config": {"text": "Sign in"}},
        {"step_type": StepType.BROWSER_EXTRACT, "config": {"selector": "#total", "output_variable": "greeting"}},
    ])
    await WorkflowEngine(db, StepExecutor(BrowserSession())).execute(
        workflow, run, {"email": "ada@example.com"}
    )

    await db.refresh(run)
    assert run.status == WorkflowRunStatus.COMPLETED, run.error_message
    assert run.outputs["s3"] == {"greeting": "Welcome ada@example.com"}
