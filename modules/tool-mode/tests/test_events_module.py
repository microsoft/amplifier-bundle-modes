"""Tests for amplifier_module_tool_mode.events module."""

from __future__ import annotations

from amplifier_module_tool_mode.events import (
    ALL_EVENTS,
    MODE_ACTIVATED,
    MODE_ACTIVATION_GATED,
    MODE_CHANGED,
    MODE_CLEARED,
    MODE_TRANSITION_DENIED,
)


def test_event_constants_have_correct_values() -> None:
    """Each event constant must equal its expected mode:* string."""
    assert MODE_ACTIVATED == "mode:activated"
    assert MODE_CLEARED == "mode:cleared"
    assert MODE_CHANGED == "mode:changed"
    assert MODE_TRANSITION_DENIED == "mode:transition_denied"
    assert MODE_ACTIVATION_GATED == "mode:activation_gated"


def test_all_events_contains_five_events() -> None:
    """ALL_EVENTS must be a list of exactly 5 mode:* strings."""
    assert isinstance(ALL_EVENTS, list)
    assert len(ALL_EVENTS) == 5
    assert "mode:activated" in ALL_EVENTS
    assert "mode:cleared" in ALL_EVENTS
    assert "mode:changed" in ALL_EVENTS
    assert "mode:transition_denied" in ALL_EVENTS
    assert "mode:activation_gated" in ALL_EVENTS
