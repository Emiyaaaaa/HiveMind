"""Explicit recoverable tool failure contract for agent feedback."""

from __future__ import annotations

import re
from typing import Any

_CODE_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_MAX_PUBLIC_MESSAGE_LEN = 512

MCP_TOOL_ERROR_PUBLIC_MESSAGE = (
    "The MCP tool returned an error. "
    "Revise the request or choose another tool."
)


class RecoverableToolError(Exception):
    """Tool failure that may be safely surfaced to the agent as an observation."""

    def __init__(
        self,
        *,
        code: str,
        public_message: str,
        internal_message: str | None = None,
    ) -> None:
        if not _CODE_PATTERN.match(code):
            raise ValueError(f"invalid recoverable tool error code: {code!r}")
        if len(public_message) > _MAX_PUBLIC_MESSAGE_LEN:
            public_message = public_message[:_MAX_PUBLIC_MESSAGE_LEN]
        super().__init__(internal_message or public_message)
        self.code = code
        self.public_message = public_message


def build_safe_tool_error_observation(
    *,
    tool_name: str,
    exc: RecoverableToolError,
) -> dict[str, Any]:
    """Build a structured, safe tool error observation for the agent loop."""
    return {
        "ok": False,
        "error": {
            "type": "recoverable_tool_error",
            "code": exc.code,
            "tool": tool_name,
            "message": exc.public_message,
        },
    }
