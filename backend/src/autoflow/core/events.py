"""
AutoFlow Domain Events
In-process event bus for domain events. Designed to upgrade to Redis Streams.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from autoflow.core.logging import get_logger

logger = get_logger(__name__)


# ─── Base Event ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DomainEvent:
    """
    Base class for all AutoFlow domain events.

    Events are immutable records of things that happened.
    They are used for:
    - In-process event bus (current)
    - Event sourcing for workflow history
    - Future: Redis Streams for distributed event processing
    """

    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def event_type(self) -> str:
        return self.__class__.__name__

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dict for storage/transmission."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            **{
                k: str(v) if isinstance(v, uuid.UUID) else v
                for k, v in self.__dataclass_fields__.items()  # type: ignore[attr-defined]
                if k not in ("event_id", "occurred_at")
            },
        }


# ─── Recording Events ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RecordingStarted(DomainEvent):
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    source: str = "browser_extension"


@dataclass(frozen=True)
class RecordingEventIngested(DomainEvent):
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    event_count: int = 0


@dataclass(frozen=True)
class RecordingStopped(DomainEvent):
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    total_events: int = 0


@dataclass(frozen=True)
class SemanticConversionCompleted(DomainEvent):
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    action_count: int = 0


# ─── Workflow Events ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkflowCreated(DomainEvent):
    workflow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""


@dataclass(frozen=True)
class WorkflowUpdated(DomainEvent):
    workflow_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class WorkflowExecutionStarted(DomainEvent):
    workflow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass(frozen=True)
class WorkflowExecutionCompleted(DomainEvent):
    workflow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    success: bool = True
    duration_ms: int = 0


@dataclass(frozen=True)
class WorkflowExecutionFailed(DomainEvent):
    workflow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    error: str = ""
    step_index: int = -1


@dataclass(frozen=True)
class WorkflowStepCompleted(DomainEvent):
    workflow_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    step_id: uuid.UUID = field(default_factory=uuid.uuid4)
    step_name: str = ""


# ─── AI Events ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IntentExtractionCompleted(DomainEvent):
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    intent: str = ""
    confidence: float = 0.0


# ─── Event Bus ────────────────────────────────────────────────────────────────

EventHandler = Callable[[DomainEvent], Coroutine[Any, Any, None]]


class EventBus:
    """
    In-process async event bus.

    Supports multiple subscribers per event type.
    Handlers run concurrently within the same event loop.

    Designed to be replaced with Redis Streams for multi-process setups.

    Usage:
        bus = EventBus()

        @bus.subscribe(RecordingStarted)
        async def on_recording_started(event: RecordingStarted):
            logger.info("Recording started", session_id=str(event.session_id))

        await bus.publish(RecordingStarted(session_id=uuid4()))
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent]) -> Callable[[EventHandler], EventHandler]:
        """Decorator to subscribe a handler to an event type."""
        def decorator(handler: EventHandler) -> EventHandler:
            self._handlers[event_type].append(handler)
            logger.debug(
                "Event handler registered",
                event_type=event_type.__name__,
                handler=handler.__name__,
            )
            return handler
        return decorator

    def on(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        """Programmatically subscribe a handler to an event type."""
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        """
        Publish an event to all registered subscribers.
        Handlers are executed concurrently.
        Failures in one handler do not affect others.
        """
        handlers = self._handlers.get(type(event), [])
        if not handlers:
            return

        logger.debug(
            "Publishing domain event",
            event_type=event.event_type,
            event_id=str(event.event_id),
            handler_count=len(handlers),
        )

        tasks = [asyncio.create_task(self._safe_invoke(handler, event)) for handler in handlers]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_invoke(self, handler: EventHandler, event: DomainEvent) -> None:
        """Invoke a handler, catching and logging any exceptions."""
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Event handler failed",
                event_type=event.event_type,
                handler=handler.__name__,
            )


# Global event bus instance
event_bus = EventBus()
