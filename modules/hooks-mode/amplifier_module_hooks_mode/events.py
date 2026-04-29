"""Event constants for the hooks-mode module.

Defines the string event identifiers emitted by hooks-mode during
tool moderation and context injection lifecycle.
"""

from __future__ import annotations

MODE_TOOL_BLOCKED: str = "mode:tool_blocked"
MODE_TOOL_WARNED: str = "mode:tool_warned"
MODE_CONTEXT_INJECTED: str = "mode:context_injected"

ALL_EVENTS: list[str] = [
    MODE_TOOL_BLOCKED,
    MODE_TOOL_WARNED,
    MODE_CONTEXT_INJECTED,
]
