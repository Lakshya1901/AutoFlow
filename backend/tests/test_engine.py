"""
Tests — Workflow engine: step ordering, safe conditions, browser replay
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoflow.execution.browser import BrowserSession, ElementNotFoundError
from autoflow.workflows.engine import StepExecutor, WorkflowEngine, evaluate_condition
from autoflow.workflows.models import (
    StepType,
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStep,
)

# ─── Fake Playwright page ─────────────────────────────────────────────────────


class FakeLocator:
    def __init__(self, page: FakePage, key: str | None) -> None:
        self._page, self._key = page, key

    async def count(self) -> int:
        return 1 if self._key in self._page.elements else 0

    @property
    def first(self) -> FakeLocator:
        return self

    async def click(self) -> None:
        self._page.actions.append(("click", self._key))

    async def fill(self, value: str) -> None:
        self._page.actions.append(("fill", self._key, value))

    async def inner_text(self) -> str:
        return self._page.elements[self._key]


class FakePage:
    """Elements are keyed by how they'd be found: 'label:Email', 'text:Submit', 'css:#total'."""

    def __init__(self, elements: dict[str, str]) -> None:
        self.elements = elements
        self.actions: list[tuple[Any, ...]] = []
        self.url = "about:blank"

    async def goto(self, url: str, wait_until: str = "load") -> None:
        self.url = url
        self.actions.append(("goto", url))

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, f"css:{selector}")

    def get_by_label(self, label: str, exact: bool = False) -> FakeLocator:
        return FakeLocator(self, f"label:{label}")

    def get_by_role(self, role: str, name: str) -> FakeLocator:
        return FakeLocator(self, f"role:{role}:{name}")

    def get_by_placeholder(self, text: str) -> FakeLocator:
        return FakeLocator(self, f"placeholder:{text}")

    def get_by_text(self, text: str, exact: bool = False) -> FakeLocator:
        return FakeLocator(self, f"text:{text}")


# ─── Conditions ───────────────────────────────────────────────────────────────

CONTEXT = {"variables": {"amount": 120, "region": "EU"}, "outputs": {"step_1": {"ok": True}}}


@pytest.mark.parametrize("expression,expected", [
    ("variables.amount > 100", True),
    ("variables.amount > 100 and variables.region == 'US'", False),
    ("variables.region in ['EU', 'UK']", True),
    ("not outputs['step_1']['ok']", False),
    ("0 < variables.amount <= 120", True),
])
def test_conditions_evaluate(expression: str, expected: bool) -> None:
    assert evaluate_condition(expression, CONTEXT) is expected


@pytest.mark.parametrize("expression", [
    "__import__('os').system('true')",
    "variables.__class__",
    "().__class__.__bases__[0].__subclasses__()",
    "open('/etc/passwd')",
    "unknown_name == 1",
])
def test_conditions_reject_code_execution(expression: str) -> None:
    with pytest.raises((ValueError, NameError, TypeError)):
        evaluate_condition(expression, CONTEXT)


# ─── Browser session ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_locate_prefers_semantic_label_then_falls_back_to_text() -> None:
    page = FakePage({"label:Email": "", "text:Sign in": ""})
    session = BrowserSession(page=page)
    await (await session.locate({"aria_label": "Email"})).fill("a@b.com")
    await (await session.locate({"aria_label": "Missing", "text": "Sign in"})).click()
    assert page.actions == [("fill", "label:Email", "a@b.com"), ("click", "text:Sign in")]


@pytest.mark.asyncio
async def test_locate_reports_strategies_tried() -> None:
    session = BrowserSession(page=FakePage({}))
    with pytest.raises(ElementNotFoundError, match="selector, label"):
        await session.locate({"selector": "#x", "aria_label": "Y"})


# ─── Engine ───────────────────────────────────────────────────────────────────


async def _make_run(db: AsyncSession, steps: list[dict[str, Any]]) -> tuple[Workflow, WorkflowRun]:
    workflow = Workflow(name="Login and read total")
    db.add(workflow)
    await db.flush()
    for i, spec in enumerate(steps):
        db.add(WorkflowStep(workflow_id=workflow.id, step_key=f"s{i}", name=f"step {i}", position=i, **spec))
    run = WorkflowRun(workflow_id=workflow.id)
    db.add(run)
    await db.flush()
    loaded = await db.execute(
        select(Workflow).where(Workflow.id == workflow.id).execution_options(populate_existing=True)
    )
    workflow = loaded.scalar_one()
    await db.refresh(workflow, ["steps", "variables"])
    return workflow, run


@pytest.mark.asyncio
async def test_engine_replays_every_step_in_order_on_one_page(db: AsyncSession) -> None:
    page = FakePage({"label:Email": "", "role:button:Sign in": "", "css:#total": " 42.00 "})
    workflow, run = await _make_run(db, [
        {"step_type": StepType.BROWSER_NAVIGATE, "config": {"url": "https://app.test/login"}},
        {"step_type": StepType.BROWSER_INPUT, "config": {"aria_label": "Email", "value": "{{variables.email}}"}},
        {"step_type": StepType.BROWSER_CLICK, "config": {"aria_label": "Sign in", "role": "button"}},
        {"step_type": StepType.BROWSER_EXTRACT, "config": {"selector": "#total", "output_variable": "total"}},
    ])
    engine = WorkflowEngine(db, StepExecutor(BrowserSession(page=page)))
    await engine.execute(workflow, run, {"email": "ada@example.com"})

    await db.refresh(run)
    assert run.status == WorkflowRunStatus.COMPLETED, run.error_message
    assert page.actions == [
        ("goto", "https://app.test/login"),
        ("fill", "label:Email", "ada@example.com"),
        ("click", "role:button:Sign in"),
    ]
    assert run.outputs["s3"] == {"total": "42.00"}
    assert [log["step_key"] for log in run.step_logs] == ["s0", "s1", "s2", "s3"]


@pytest.mark.asyncio
async def test_missing_element_fails_run_at_that_step(db: AsyncSession) -> None:
    workflow, run = await _make_run(db, [
        {"step_type": StepType.BROWSER_NAVIGATE, "config": {"url": "https://app.test"}},
        {"step_type": StepType.BROWSER_CLICK, "config": {"text": "Not there"}},
        {"step_type": StepType.BROWSER_CLICK, "config": {"text": "Never reached"}},
    ])
    await WorkflowEngine(db, StepExecutor(BrowserSession(page=FakePage({})))).execute(workflow, run)

    await db.refresh(run)
    assert run.status == WorkflowRunStatus.FAILED
    assert run.error_step_key == "s1"
    assert "No element matched" in run.error_message


@pytest.mark.asyncio
async def test_on_error_continue_moves_to_next_step(db: AsyncSession) -> None:
    page = FakePage({"text:Next": ""})
    workflow, run = await _make_run(db, [
        {"step_type": StepType.BROWSER_CLICK, "config": {"text": "Optional banner"}, "on_error": "continue"},
        {"step_type": StepType.BROWSER_CLICK, "config": {"text": "Next"}},
    ])
    await WorkflowEngine(db, StepExecutor(BrowserSession(page=page))).execute(workflow, run)

    await db.refresh(run)
    assert run.status == WorkflowRunStatus.COMPLETED
    assert page.actions == [("click", "text:Next")]
