"""
Connector System — Base Classes
Plugin interface for all AutoFlow connectors.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from autoflow.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ConnectorAction:
    """
    Defines a single action that a connector can perform.

    Actions are discoverable and shown in the workflow editor.
    """

    name: str                         # Unique action name, e.g., "send_email"
    display_name: str                 # Human-readable, e.g., "Send Email"
    description: str
    input_schema: dict[str, Any]      # JSON Schema for input parameters
    output_schema: dict[str, Any]     # JSON Schema for outputs
    requires_auth: bool = True
    is_destructive: bool = False      # Triggers approval checkpoint prompt
    example_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorConfig:
    """Authentication and configuration for a connector instance."""

    connector_id: str
    credentials: dict[str, str]       # Encrypted at rest
    settings: dict[str, Any] = field(default_factory=dict)


class ConnectorExecutionResult:
    """Result from executing a connector action."""

    def __init__(
        self,
        success: bool,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.success = success
        self.outputs = outputs or {}
        self.error = error
        self.metadata = metadata or {}

    @classmethod
    def ok(cls, outputs: dict[str, Any] | None = None, **kwargs: Any) -> ConnectorExecutionResult:
        return cls(success=True, outputs={**(outputs or {}), **kwargs})

    @classmethod
    def fail(cls, error: str) -> ConnectorExecutionResult:
        return cls(success=False, error=error)


class BaseConnector(abc.ABC):
    """
    Abstract base class for all AutoFlow connectors.

    To create a new connector:
    1. Subclass BaseConnector
    2. Implement all abstract methods
    3. Register in ConnectorRegistry

    Connectors are discovered automatically if placed in autoflow/connectors/.
    """

    @property
    @abc.abstractmethod
    def connector_id(self) -> str:
        """Unique connector identifier, e.g., 'gmail', 'google_drive'."""

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        """Human-readable connector name."""

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Brief description of what this connector does."""

    @property
    @abc.abstractmethod
    def actions(self) -> list[ConnectorAction]:
        """List of actions this connector supports."""

    @abc.abstractmethod
    async def execute(
        self,
        action_name: str,
        config: dict[str, Any],
        credentials: dict[str, str],
    ) -> ConnectorExecutionResult:
        """
        Execute a connector action.

        Args:
            action_name: The action to execute (must be in self.actions)
            config: Resolved action configuration (variables already substituted)
            credentials: Decrypted credentials for this connector

        Returns:
            ConnectorExecutionResult with success/failure and output data
        """

    @abc.abstractmethod
    async def validate_credentials(self, credentials: dict[str, str]) -> bool:
        """Test if the provided credentials are valid."""

    def get_action(self, action_name: str) -> ConnectorAction | None:
        """Get a specific action definition by name."""
        return next((a for a in self.actions if a.name == action_name), None)

    def __repr__(self) -> str:
        return f"<Connector: {self.connector_id}>"


# ─── Registry ─────────────────────────────────────────────────────────────────

class ConnectorRegistry:
    """
    Registry for all available connectors.

    Connectors register themselves here at import time.
    The registry is used by the workflow editor and executor.
    """

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        """Register a connector instance."""
        self._connectors[connector.connector_id] = connector
        logger.info("Connector registered", connector_id=connector.connector_id)

    def get(self, connector_id: str) -> BaseConnector | None:
        """Get a connector by ID."""
        return self._connectors.get(connector_id)

    def all(self) -> list[BaseConnector]:
        """Get all registered connectors."""
        return list(self._connectors.values())

    def action_exists(self, connector_id: str, action_name: str) -> bool:
        """Check if a connector action exists."""
        connector = self.get(connector_id)
        if not connector:
            return False
        return connector.get_action(action_name) is not None


# Global registry
registry = ConnectorRegistry()
