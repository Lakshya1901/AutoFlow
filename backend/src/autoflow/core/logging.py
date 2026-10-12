"""
AutoFlow Structured Logging
Configures structlog for JSON-formatted, context-aware logging.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from autoflow.core.config import get_settings


def configure_logging() -> None:
    """
    Configure structlog with appropriate processors for the environment.

    - Development: Pretty-printed console output with colors
    - Production: JSON-formatted output for log aggregation
    """
    settings = get_settings()

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.is_development:
        # Human-readable output for development
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # JSON output for production log aggregation (Datadog, Loki, etc.)
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        # stdlib loggers: add_logger_name needs a logger with .name, and levels follow logging config
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging to route through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.is_development else logging.INFO,
    )
    # Driver-level DEBUG chatter (every SQL cursor call) drowns out application logs
    for noisy in ("aiosqlite", "asyncio", "httpcore", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Usage:
        from autoflow.core.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Recording started", recording_id=str(session_id))
    """
    return structlog.get_logger(name)
