"""Tests for amplifier_module_hooks_mode.events module."""

from __future__ import annotations

from amplifier_module_hooks_mode.events import (
    ALL_EVENTS,
    MODE_CONTEXT_INJECTED,
    MODE_TOOL_BLOCKED,
    MODE_TOOL_WARNED,
)


def test_mode_tool_blocked_value() -> None:
    """MODE_TOOL_BLOCKED must equal 'mode:tool_blocked'."""
    assert MODE_TOOL_BLOCKED == "mode:tool_blocked"


def test_mode_tool_warned_value() -> None:
    """MODE_TOOL_WARNED must equal 'mode:tool_warned'."""
    assert MODE_TOOL_WARNED == "mode:tool_warned"


def test_mode_context_injected_value() -> None:
    """MODE_CONTEXT_INJECTED must equal 'mode:context_injected'."""
    assert MODE_CONTEXT_INJECTED == "mode:context_injected"


def test_all_events_is_list() -> None:
    """ALL_EVENTS must be a list."""
    assert isinstance(ALL_EVENTS, list)


def test_all_events_length() -> None:
    """ALL_EVENTS must contain exactly 3 events."""
    assert len(ALL_EVENTS) == 3


def test_all_events_contains_mode_tool_blocked() -> None:
    """ALL_EVENTS must contain MODE_TOOL_BLOCKED."""
    assert MODE_TOOL_BLOCKED in ALL_EVENTS


def test_all_events_contains_mode_tool_warned() -> None:
    """ALL_EVENTS must contain MODE_TOOL_WARNED."""
    assert MODE_TOOL_WARNED in ALL_EVENTS


def test_all_events_contains_mode_context_injected() -> None:
    """ALL_EVENTS must contain MODE_CONTEXT_INJECTED."""
    assert MODE_CONTEXT_INJECTED in ALL_EVENTS
