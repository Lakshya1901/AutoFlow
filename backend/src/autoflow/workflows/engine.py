"""
Workflows Domain — Execution Engine
Core workflow execution logic with step dispatch, variable resolution, and event emission.
"""

from __future__ import annotations

import ast
import itertools
import operator
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from autoflow.core.events import (
    WorkflowExecutionCompleted,
    WorkflowExecutionFailed,
    WorkflowExecutionStarted,
    WorkflowStepCompleted,
    event_bus,
)
from autoflow.core.logging import get_logger
from autoflow.execution.browser import BrowserSession
from autoflow.workflows.models import (
    StepType,
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStep,
)

logger = get_logger(__name__)


# ─── Variable Resolver ────────────────────────────────────────────────────────

class VariableResolver:
    """
    Resolves {{variable_name}} placeholders in step configurations.

    Supports nested paths: {{outputs.step_001.filename}}
    """

    _PATTERN = re.compile(r"\{\{([^}]+)\}\}")

    def __init__(self, context: dict[str, Any]) -> None:
        self._context = context

    def resolve_string(self, value: str) -> str:
        """Replace all {{variable}} placeholders in a string."""
        def replacer(match: re.Match) -> str:
            key = match.group(1).strip()
            resolved = self._resolve_path(key)
            return str(resolved) if resolved is not None else match.group(0)

        return self._PATTERN.sub(replacer, value)

    def resolve(self, obj: Any) -> Any:
        """Recursively resolve variables in any object (dict, list, str)."""
        if isinstance(obj, str):
            return self.resolve_string(obj)
        elif isinstance(obj, dict):
            return {k: self.resolve(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.resolve(item) for item in obj]
        return obj

    def _resolve_path(self, path: str) -> Any:
        """Resolve a dotted path like 'outputs.step_001.filename'."""
        parts = path.split(".")
        current = self._context
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def set(self, key: str, value: Any) -> None:
        """Set a value in the resolution context."""
        self._context[key] = value


# ─── Condition Evaluation ─────────────────────────────────────────────────────

_COMPARATORS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge, ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def evaluate_condition(expression: str, context: dict[str, Any]) -> Any:
    """
    Evaluate a step condition without eval().

    Allows literals, context lookups (``variables.count``, ``outputs["step_1"]``),
    comparisons and ``and``/``or``/``not``. Anything else (calls, attribute access on
    objects, dunders) is rejected, so user-authored workflows can't execute code.
    """
    def ev(node: ast.AST) -> Any:
        match node:
            case ast.Expression(body=body):
                return ev(body)
            case ast.Constant(value=value):
                return value
            case ast.Name(id=name):
                if name not in context:
                    raise NameError(f"unknown name '{name}'")
                return context[name]
            case ast.Attribute(value=base, attr=attr) if not attr.startswith("_"):
                container = ev(base)
                if not isinstance(container, dict):
                    raise TypeError(f"cannot read '{attr}' from {type(container).__name__}")
                return container.get(attr)
            case ast.Subscript(value=base, slice=key):
                container, k = ev(base), ev(key)
                if not isinstance(container, (dict, list, tuple, str)):
                    raise TypeError(f"cannot index {type(container).__name__}")
                return container[k]
            case ast.BoolOp(op=ast.And(), values=values):
                return all(ev(v) for v in values)
            case ast.BoolOp(op=ast.Or(), values=values):
                return any(ev(v) for v in values)
            case ast.UnaryOp(op=ast.Not(), operand=operand):
                return not ev(operand)
            case ast.Compare(left=left, ops=ops, comparators=rights):
                current = ev(left)
                for op, right in zip(ops, rights, strict=True):
                    value = ev(right)
                    if not _COMPARATORS[type(op)](current, value):
                        return False
                    current = value
                return True
            case ast.List(elts=elts) | ast.Tuple(elts=elts):
                return [ev(e) for e in elts]
        raise ValueError(f"unsupported expression element: {type(node).__name__}")

    return ev(ast.parse(expression, mode="eval"))


# ─── Step Executors ───────────────────────────────────────────────────────────

class StepExecutionResult:
    """Result of a step execution."""

    def __init__(
        self,
        success: bool,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.outputs = outputs or {}
        self.error = error

    @classmethod
    def ok(cls, outputs: dict[str, Any] | None = None) -> StepExecutionResult:
        return cls(success=True, outputs=outputs)

    @classmethod
    def fail(cls, error: str) -> StepExecutionResult:
        return cls(success=False, error=error)


class StepExecutor:
    """
    Dispatches step execution to the appropriate handler based on step type.

    Browser steps run on a Playwright page shared across the whole run.
    """

    def __init__(self, browser_session: BrowserSession | None = None) -> None:
        self._browser_session = browser_session or BrowserSession()

    async def close(self) -> None:
        await self._browser_session.close()

    async def execute(
        self,
        step: WorkflowStep,
        resolver: VariableResolver,
        run_id: uuid.UUID,
    ) -> StepExecutionResult:
        """Execute a single workflow step."""
        config = resolver.resolve(step.config or {})

        logger.info(
            "Executing step",
            run_id=str(run_id),
            step_key=step.step_key,
            step_type=step.step_type,
        )

        match step.step_type:
            case StepType.BROWSER_NAVIGATE:
                return await self._browser_navigate(config)
            case StepType.BROWSER_CLICK:
                return await self._browser_click(config)
            case StepType.BROWSER_INPUT:
                return await self._browser_input(config)
            case StepType.BROWSER_EXTRACT:
                return await self._browser_extract(config)
            case StepType.BROWSER_DOWNLOAD:
                return await self._browser_download(config)
            case StepType.FILE_RENAME:
                return await self._file_rename(config)
            case StepType.FILE_CREATE_FOLDER:
                return await self._file_create_folder(config)
            case StepType.FILE_MOVE:
                return await self._file_move(config)
            case StepType.APPROVAL_CHECKPOINT:
                return await self._approval_checkpoint(config, step, run_id)
            case StepType.NOTIFICATION:
                return await self._notification(config)
            case StepType.HTTP_REQUEST:
                return await self._http_request(config)
            case StepType.CONDITION:
                return await self._condition(config, resolver)
            case StepType.WAIT:
                return await self._wait(config)
            case _:
                return StepExecutionResult.ok({"message": f"Step type {step.step_type} acknowledged"})

    async def _browser(self, action: str, config: dict) -> StepExecutionResult:
        """Run a browser action on the run's shared page, turning failures into step errors."""
        try:
            return StepExecutionResult.ok(await getattr(self._browser_session, action)(config))
        except Exception as e:
            logger.warning("Browser step failed", action=action, error=str(e))
            return StepExecutionResult.fail(f"browser {action} failed: {e}")

    async def _browser_navigate(self, config: dict) -> StepExecutionResult:
        """Navigate browser to a URL."""
        url = config.get("url")
        if not url:
            return StepExecutionResult.fail("browser_navigate requires 'url' in config")
        try:
            return StepExecutionResult.ok(await self._browser_session.navigate(url))
        except Exception as e:
            return StepExecutionResult.fail(f"browser navigate failed: {e}")

    async def _browser_click(self, config: dict) -> StepExecutionResult:
        """Click a UI element using semantic identification."""
        return await self._browser("click", config)

    async def _browser_input(self, config: dict) -> StepExecutionResult:
        """Type text into a form field."""
        return await self._browser("fill", config)

    async def _browser_extract(self, config: dict) -> StepExecutionResult:
        """Extract the text of a page element into an output variable."""
        return await self._browser("extract", config)

    async def _browser_download(self, config: dict) -> StepExecutionResult:
        """Click an element that triggers a download and save the file."""
        return await self._browser("download", config)

    async def _file_rename(self, config: dict) -> StepExecutionResult:
        """Rename a file."""
        import os
        src = config.get("source")
        dest = config.get("destination")
        if not src or not dest:
            return StepExecutionResult.fail("file_rename requires source and destination")
        try:
            os.rename(src, dest)
            return StepExecutionResult.ok({"renamed_to": dest})
        except Exception as e:
            return StepExecutionResult.fail(str(e))

    async def _file_create_folder(self, config: dict) -> StepExecutionResult:
        """Create a directory."""
        import os
        path = config.get("path")
        if not path:
            return StepExecutionResult.fail("file_create_folder requires path")
        os.makedirs(path, exist_ok=True)
        return StepExecutionResult.ok({"created_path": path})

    async def _file_move(self, config: dict) -> StepExecutionResult:
        """Move a file."""
        import shutil
        src = config.get("source")
        dest = config.get("destination")
        if not src or not dest:
            return StepExecutionResult.fail("file_move requires source and destination")
        try:
            shutil.move(src, dest)
            return StepExecutionResult.ok({"moved_to": dest})
        except Exception as e:
            return StepExecutionResult.fail(str(e))

    async def _approval_checkpoint(
        self, config: dict, step: WorkflowStep, run_id: uuid.UUID  # noqa: ARG002 - uniform handler signature
    ) -> StepExecutionResult:
        """Pause execution for human approval."""
        # This is handled at the engine level — the engine pauses and waits
        return StepExecutionResult.ok({"awaiting_approval": True, "run_id": str(run_id)})

    async def _notification(self, config: dict) -> StepExecutionResult:
        """Send a notification (stub — real connectors handle this)."""
        channel = config.get("channel", "in-app")
        message = config.get("message", "")
        logger.info("Notification", channel=channel, message=message[:100])
        return StepExecutionResult.ok({"notified": True, "channel": channel})

    async def _http_request(self, config: dict) -> StepExecutionResult:
        """Make an HTTP request."""
        import httpx
        method = config.get("method", "GET").upper()
        url = config.get("url")
        if not url:
            return StepExecutionResult.fail("http_request requires url")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=config.get("headers", {}),
                    json=config.get("body"),
                    timeout=30,
                )
                return StepExecutionResult.ok({
                    "status_code": response.status_code,
                    "response_body": response.text[:10000],
                })
        except Exception as e:
            return StepExecutionResult.fail(str(e))

    async def _condition(self, config: dict, resolver: VariableResolver) -> StepExecutionResult:
        """Evaluate a condition expression."""
        expression = config.get("expression", "True")
        try:
            result = bool(evaluate_condition(expression, resolver._context))
            return StepExecutionResult.ok({"condition_result": result})
        except Exception as e:
            return StepExecutionResult.fail(f"Condition evaluation failed: {e}")

    async def _wait(self, config: dict) -> StepExecutionResult:
        """Wait for a specified duration."""
        import asyncio
        seconds = config.get("seconds", 1)
        await asyncio.sleep(min(seconds, 300))  # Max 5 minutes
        return StepExecutionResult.ok({"waited_seconds": seconds})


# ─── Workflow Engine ──────────────────────────────────────────────────────────

class WorkflowEngine:
    """
    Core workflow execution engine.

    Executes workflow steps sequentially, handling:
    - Variable resolution ({{variable}} interpolation)
    - Control flow (conditions, loops, branches)
    - Error handling (stop, continue, retry)
    - Human-in-the-loop checkpoints
    - Event emission for every state transition
    """

    def __init__(self, db: AsyncSession, executor: StepExecutor | None = None) -> None:
        self._db = db
        self._executor = executor or StepExecutor()

    async def execute(
        self,
        workflow: Workflow,
        run: WorkflowRun,
        variable_values: dict[str, Any] | None = None,
    ) -> WorkflowRun:
        """
        Execute a workflow run.

        The run object is updated in the database as execution progresses,
        enabling real-time monitoring from the frontend.
        """
        try:
            return await self._execute(workflow, run, variable_values)
        finally:
            await self._executor.close()

    async def _execute(
        self,
        workflow: Workflow,
        run: WorkflowRun,
        variable_values: dict[str, Any] | None,
    ) -> WorkflowRun:
        start_time = datetime.now(UTC)

        # Initialize execution context
        context: dict[str, Any] = {
            "variables": {**{v.name: v.default_value for v in workflow.variables}},
            "outputs": {},
            "run_id": str(run.id),
            "workflow_id": str(workflow.id),
        }

        # Override with provided variable values
        if variable_values:
            context["variables"].update(variable_values)

        resolver = VariableResolver(context)
        step_logs: list[dict[str, Any]] = []

        # Update run to running
        await self._update_run(
            run.id,
            status=WorkflowRunStatus.RUNNING,
            started_at=start_time,
        )

        await event_bus.publish(
            WorkflowExecutionStarted(workflow_id=workflow.id, run_id=run.id)
        )

        # Get ordered steps
        steps = sorted(workflow.steps, key=lambda s: s.position)

        if not steps:
            await self._complete_run(run.id, workflow.id, start_time, {}, step_logs)
            return run

        current_step_key = steps[0].step_key if steps else None
        step_map = {s.step_key: s for s in steps}
        # Steps without an explicit next_step_key continue in position order
        following = {a.step_key: b.step_key for a, b in itertools.pairwise(steps)}

        def next_key(step: WorkflowStep, *, succeeded: bool) -> str | None:
            explicit = step.on_success_step_key if succeeded else None
            return explicit or step.next_step_key or following.get(step.step_key)
        completed_steps: list[str] = []

        # Main execution loop
        while current_step_key:
            step = step_map.get(current_step_key)
            if not step or step.is_disabled:
                # Skip disabled steps; a dangling reference ends the run
                current_step_key = next_key(step, succeeded=False) if step else None
                continue

            # Check for approval checkpoint
            if step.requires_approval:
                await self._update_run(
                    run.id,
                    status=WorkflowRunStatus.WAITING_FOR_APPROVAL,
                    current_step_key=current_step_key,
                )
                # Approval is handled externally via the API
                # This run is suspended until approved
                return run

            # Update current step in run
            await self._update_run(
                run.id,
                current_step_key=current_step_key,
                completed_steps=completed_steps,
            )

            # Execute the step (with retry support)
            result = await self._execute_with_retry(step, resolver, run.id)

            step_log = {
                "step_key": step.step_key,
                "step_name": step.name,
                "success": result.success,
                "outputs": result.outputs,
                "error": result.error,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            step_logs.append(step_log)

            if result.success:
                # Store step outputs in context
                context["outputs"][step.step_key] = result.outputs
                completed_steps.append(step.step_key)

                await event_bus.publish(
                    WorkflowStepCompleted(
                        workflow_id=workflow.id,
                        run_id=run.id,
                        step_id=step.id,
                        step_name=step.name,
                    )
                )

                # Determine next step
                current_step_key = next_key(step, succeeded=True)

            else:
                # Step failed
                match step.on_error:
                    case "continue":
                        logger.warning(
                            "Step failed, continuing",
                            step_key=step.step_key,
                            error=result.error,
                        )
                        current_step_key = next_key(step, succeeded=False)
                    case "stop" | _:
                        # Stop execution
                        await self._fail_run(
                            run.id,
                            workflow.id,
                            error=result.error or "Step execution failed",
                            error_step_key=step.step_key,
                            step_logs=step_logs,
                        )
                        return run

        # All steps completed successfully
        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        await self._complete_run(
            run.id, workflow.id, start_time, context.get("outputs", {}), step_logs
        )

        await event_bus.publish(
            WorkflowExecutionCompleted(
                workflow_id=workflow.id,
                run_id=run.id,
                success=True,
                duration_ms=duration_ms,
            )
        )

        return run

    async def _execute_with_retry(
        self,
        step: WorkflowStep,
        resolver: VariableResolver,
        run_id: uuid.UUID,
    ) -> StepExecutionResult:
        """Execute a step with retry logic."""
        import asyncio

        last_error = None
        for attempt in range(step.max_retries + 1):
            if attempt > 0:
                logger.info(
                    "Retrying step",
                    step_key=step.step_key,
                    attempt=attempt,
                    max_retries=step.max_retries,
                )
                await asyncio.sleep(step.retry_delay_seconds)

            try:
                result = await self._executor.execute(step, resolver, run_id)
                if result.success:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                logger.exception("Step raised exception", step_key=step.step_key)

        return StepExecutionResult.fail(last_error or "Max retries exceeded")

    async def _update_run(self, run_id: uuid.UUID, **values: Any) -> None:
        """Update a run record with new values."""
        await self._db.execute(
            update(WorkflowRun).where(WorkflowRun.id == run_id).values(**values)
        )

    async def _complete_run(
        self,
        run_id: uuid.UUID,
        workflow_id: uuid.UUID,
        start_time: datetime,
        outputs: dict,
        step_logs: list,
    ) -> None:
        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        await self._update_run(
            run_id,
            status=WorkflowRunStatus.COMPLETED,
            completed_at=end_time,
            duration_ms=duration_ms,
            outputs=outputs,
            step_logs=step_logs,
        )

        # Update workflow stats
        from sqlalchemy import select
        result = await self._db.execute(
            select(Workflow).where(Workflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        if workflow:
            await self._db.execute(
                update(Workflow)
                .where(Workflow.id == workflow_id)
                .values(
                    total_runs=Workflow.total_runs + 1,
                    successful_runs=Workflow.successful_runs + 1,
                )
            )

    async def _fail_run(
        self,
        run_id: uuid.UUID,
        workflow_id: uuid.UUID,
        error: str,
        error_step_key: str | None,
        step_logs: list,
    ) -> None:
        await self._update_run(
            run_id,
            status=WorkflowRunStatus.FAILED,
            completed_at=datetime.now(UTC),
            error_message=error,
            error_step_key=error_step_key,
            step_logs=step_logs,
        )

        await self._db.execute(
            update(Workflow)
            .where(Workflow.id == workflow_id)
            .values(
                total_runs=Workflow.total_runs + 1,
                failed_runs=Workflow.failed_runs + 1,
            )
        )

        await event_bus.publish(
            WorkflowExecutionFailed(
                workflow_id=workflow_id,
                run_id=run_id,
                error=error,
            )
        )
