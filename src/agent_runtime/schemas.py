from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def classify_tool_exception(exc: Exception) -> tuple[str, bool]:
    """Map runtime exceptions to a stable error type and retry decision."""

    if isinstance(exc, TimeoutError):
        return "timeout", True
    if isinstance(exc, ConnectionError):
        return "connection_error", True
    if isinstance(exc, PermissionError):
        return "permission_error", False
    if isinstance(exc, (TypeError, ValueError)):
        return "invalid_request", False
    return "unknown_error", False


@dataclass
class ToolResult:
    """Small structured result object for the first tool-calling prototype."""

    tool: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "error_type": self.error_type,
            "retryable": self.retryable,
        }
