from __future__ import annotations


class DciPocError(RuntimeError):
    """Base exception for hard POC failures."""


class ConfigurationError(DciPocError):
    """Raised when local configuration is invalid."""


class ApprovedSourceError(DciPocError):
    """Raised when approved-source configuration or requests are invalid."""


class ToolDispatchError(DciPocError):
    """Raised when a tool call cannot be dispatched safely."""

