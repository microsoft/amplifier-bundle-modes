"""Regression test: docs/diagrams/mode-lifecycle.dot must exist and catalogue
all 8 mode:* event names.

The lifecycle diagram is the authoritative state-machine reference for the
mode sub-system.  These tests guard against the file being accidentally
removed or losing event entries through future edits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# modules/hooks-mode/tests/ → [0]=tests [1]=hooks-mode [2]=modules [3]=bundle root
BUNDLE_ROOT = Path(__file__).resolve().parents[3]
LIFECYCLE_DOT = BUNDLE_ROOT / "docs" / "diagrams" / "mode-lifecycle.dot"

# All 8 mode:* event names that must appear in the state-machine diagram.
REQUIRED_EVENTS = [
    "mode:activated",
    "mode:changed",
    "mode:cleared",
    "mode:transition_denied",
    "mode:activation_gated",
    "mode:tool_blocked",
    "mode:tool_warned",
    "mode:context_injected",
]


def test_lifecycle_diagram_exists() -> None:
    """docs/diagrams/mode-lifecycle.dot must exist in the bundle."""
    assert LIFECYCLE_DOT.is_file(), (
        f"Expected state-machine diagram missing: {LIFECYCLE_DOT}\n"
        "Create docs/diagrams/mode-lifecycle.dot per the task-13 spec."
    )


@pytest.mark.parametrize("event_name", REQUIRED_EVENTS)
def test_lifecycle_diagram_contains_event(event_name: str) -> None:
    """Every mode:* event name must appear in mode-lifecycle.dot."""
    assert LIFECYCLE_DOT.is_file(), (
        f"Expected state-machine diagram missing: {LIFECYCLE_DOT}"
    )
    content = LIFECYCLE_DOT.read_text(encoding="utf-8")
    assert event_name in content, (
        f"mode-lifecycle.dot is missing event: {event_name!r}.\n"
        f"All 8 mode:* events must appear in the diagram."
    )
