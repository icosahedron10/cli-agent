from __future__ import annotations


class CliAgentError(RuntimeError):
    """Base exception for hard application failures."""


class SettingsError(CliAgentError):
    """Raised when local settings are invalid."""


class ApprovedSourceError(CliAgentError):
    """Raised when approved-source settings or requests are invalid."""


class ToolDispatchError(CliAgentError):
    """Raised when a tool call cannot be dispatched safely."""
