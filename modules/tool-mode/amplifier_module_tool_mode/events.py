"""Event constants for the tool-mode module.

Defines the string event identifiers emitted by tool-mode during
mode activation, deactivation, and transition lifecycle.
"""

from __future__ import annotations

MODE_ACTIVATED: str = "mode:activated"
MODE_CLEARED: str = "mode:cleared"
MODE_CHANGED: str = "mode:changed"
MODE_TRANSITION_DENIED: str = "mode:transition_denied"
MODE_ACTIVATION_GATED: str = "mode:activation_gated"

ALL_EVENTS: list[str] = [
    MODE_ACTIVATED,
    MODE_CLEARED,
    MODE_CHANGED,
    MODE_TRANSITION_DENIED,
    MODE_ACTIVATION_GATED,
]
