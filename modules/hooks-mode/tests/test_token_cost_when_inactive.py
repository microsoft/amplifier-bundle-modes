"""Bounded-token-cost-when-inactive tests.

Design headline claim: when a mode is *never activated*, it contributes no
agents, no skills, and no mode context to an in-flight session — only a single
fixed "no mode is currently active" reminder, whose exact bytes are pinned in
test 4 below.

These tests enforce that invariant as CI-checked assertions.  Previously this
was verified by the ad-hoc script ``token_measurement_check.py`` at module
root; that script has been deleted and replaced by the four tests below so the
claim is checked on every test run.

Test catalogue
--------------
1. ``test_inactive_session_has_no_mode_design_agent_in_registry``
   — mode-author must never appear in the agent registry when /mode-design
     was never activated.

2. ``test_inactive_session_has_no_runtime_context_overlay_capability``
   — register_capability must never be called with ``runtime_context_overlay``
     while no mode is active.

3. ``test_inactive_session_has_no_runtime_skill_overlay_capability``
   — register_capability must never be called with ``runtime_skill_overlay``
     while no mode is active.

4. ``test_inactive_session_injects_only_the_mode_status_reminder``
   — handle_provider_request must inject exactly the fixed mode-status
     reminder (and nothing larger) when active_mode is None.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Capability names used by RuntimeOverlay (producer-neutral names after rename)
from amplifier_foundation import (
    RUNTIME_CONTEXT_OVERLAY_CAPABILITY as _CAP_CONTEXT,
    RUNTIME_SKILL_OVERLAY_CAPABILITY as _CAP_SKILLS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Three levels up from tests/ brings us to the bundle root
# (tests/ → hooks-mode/ → modules/ → amplifier-bundle-modes/)
BUNDLE_ROOT: Path = Path(__file__).resolve().parents[3]
MODES_DIR: Path = BUNDLE_ROOT / "modes"


# ---------------------------------------------------------------------------
# Shared helper — mirrors _make_coordinator in test_overlay_integration.py
# ---------------------------------------------------------------------------


def _make_coordinator(
    active_mode: str | None = None,
    agents: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a MagicMock coordinator with the surface area that overlay touches."""
    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }
    coordinator.config = {"agents": dict(agents or {})}
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.hooks.register = MagicMock()
    coordinator.hooks.unregister = MagicMock()
    coordinator.hooks.mount = MagicMock()
    coordinator.hooks.unmount = MagicMock()
    coordinator.get_capability = MagicMock(return_value=None)
    return coordinator


# ---------------------------------------------------------------------------
# Test 1 — no agent leaked into registry
# ---------------------------------------------------------------------------


def test_inactive_session_has_no_mode_design_agent_in_registry() -> None:
    """mode-author must not appear in the agent registry when mode-design is never activated.

    Scenario: create a coordinator + discovery pointing at the bundle modes
    directory (which contains mode-design.md).  Never call
    handle_mode_activated.  Assert the registry stays empty.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    coord = _make_coordinator(active_mode=None, agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    # Just constructing ModeHooks must not cause any contribution
    _hooks = ModeHooks(coord, discovery)

    agents_str = str(coord.config["agents"])
    assert "mode-author" not in agents_str, (
        "FAIL: 'mode-author' leaked into inactive session agents! "
        "Constructing ModeHooks or ModeDiscovery must never mount contributed "
        f"agents.  Agents dict: {agents_str!r}"
    )
    assert coord.config["agents"] == {}, (
        "Agent registry must be empty before any mode is activated. "
        f"Got: {coord.config['agents']!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — no runtime_context_overlay capability registered
# ---------------------------------------------------------------------------


def test_inactive_session_has_no_runtime_context_overlay_capability() -> None:
    """register_capability must never be called with runtime_context_overlay when inactive.

    Scenario: create coordinator + discovery, never activate a mode.  Assert
    that register_capability was never called with the ``runtime_context_overlay``
    capability name.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    coord = _make_coordinator(active_mode=None, agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    _hooks = ModeHooks(coord, discovery)

    # Collect all register_capability calls
    cap_names_called = [
        call.args[0] for call in coord.register_capability.call_args_list if call.args
    ]

    assert _CAP_CONTEXT not in cap_names_called, (
        f"FAIL: register_capability was called with '{_CAP_CONTEXT}' before "
        "any mode was activated.  Context capability must only be registered "
        "when the overlay applies a mode's contributions.\n"
        f"All capability registrations seen: {cap_names_called!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — no runtime_skill_overlay capability registered
# ---------------------------------------------------------------------------


def test_inactive_session_has_no_runtime_skill_overlay_capability() -> None:
    """register_capability must never be called with runtime_skill_overlay when inactive.

    Scenario: create coordinator + discovery, never activate a mode.  Assert
    that register_capability was never called with the ``runtime_skill_overlay``
    capability name.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    coord = _make_coordinator(active_mode=None, agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    _hooks = ModeHooks(coord, discovery)

    cap_names_called = [
        call.args[0] for call in coord.register_capability.call_args_list if call.args
    ]

    assert _CAP_SKILLS not in cap_names_called, (
        f"FAIL: register_capability was called with '{_CAP_SKILLS}' before "
        "any mode was activated.  Skills capability must only be registered "
        "when the overlay applies a mode's contributions.\n"
        f"All capability registrations seen: {cap_names_called!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — provider request injects the fixed mode-status reminder, nothing more
# ---------------------------------------------------------------------------

# The exact block handle_provider_request injects when no mode is active.
# Byte-for-byte, so that any growth of the inactive-session payload — a mode
# body, a schema reference, a per-mode listing — fails this test rather than
# silently costing every turn of every session that never activates a mode.
EXPECTED_NO_MODE_BLOCK: str = (
    '<system-reminder source="mode-status">\n'
    "No mode is currently active. "
    'Use `mode(operation="list")` to see available modes '
    'or `mode(operation="set", name="<name>")` to activate one.\n'
    "</system-reminder>"
)


@pytest.mark.asyncio
async def test_inactive_session_injects_only_the_mode_status_reminder() -> None:
    """An inactive session must inject the fixed mode-status reminder and nothing else.

    Scenario: create coordinator with active_mode=None, call
    handle_provider_request.  Assert the result is exactly the small fixed
    reminder block, marked ephemeral so it never accumulates.

    Contract note: this asserted ``action == "continue"`` until commit 84e3054
    ("fix(hooks-mode): inject positive mode-status reminder when no mode is
    active") deliberately replaced silence with a positive signal, so the LLM
    cannot make false claims about mode state across turns.  That commit
    updated ``test_hooks.py`` and missed this file, leaving two tests in this
    repo asserting contradictory contracts.  This one was the stale side; the
    shipped contract is the one asserted here and in
    ``test_hooks.py::test_no_active_mode_injects_status_reminder``.

    The bound, not the absence, is what this file now guards: the cost of an
    inactive session is this one constant block — currently 176 characters —
    and equality catches any attempt to grow it.
    """
    from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

    coord = _make_coordinator(active_mode=None, agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    result = await hooks.handle_provider_request("provider:request", {})

    assert result.action == "inject_context", (
        f"FAIL: handle_provider_request must return action='inject_context' when "
        f"no mode is active, but got action={result.action!r}.  "
        "The inactive session gets a positive 'no mode is active' signal."
    )

    injected = getattr(result, "context_injection", None) or ""
    assert injected == EXPECTED_NO_MODE_BLOCK, (
        "FAIL: the inactive-session injection is no longer the fixed mode-status "
        "reminder.  An inactive session must cost exactly this one constant block "
        "and nothing more.\n"
        f"  expected ({len(EXPECTED_NO_MODE_BLOCK)} chars): {EXPECTED_NO_MODE_BLOCK!r}\n"
        f"  got      ({len(injected)} chars): {injected!r}"
    )

    assert getattr(result, "ephemeral", False) is True, (
        "FAIL: the inactive-session reminder must be ephemeral, so it is not "
        "accumulated into the conversation on every turn."
    )

    # Belt and braces: the schema reference is the largest thing that could leak
    # here, and it is what the deleted token_measurement_check.py watched for.
    assert "Amplifier Mode Schema Reference" not in injected, (
        "FAIL: 'Amplifier Mode Schema Reference' leaked into inactive session context! "
        f"Injected context (first 200 chars): {injected[:200]!r}"
    )
