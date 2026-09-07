"""Regression tests for the B3 false-positive fix (Option A).

Root cause: handle_mode_cleared() called overlay.revoke() but never removed
the (now-empty) RuntimeOverlay from session_state["mode_runtime_overlay"].
On every subsequent provider:request, the B3 guard fires:
  "Mode runtime overlay exists but active_mode is None — possible
   session-resume state loss."
This is a false positive — it's the normal in-process state after /mode off.

Option A fix: _discard_overlay_if_empty() removes the overlay from
session_state when dump_state()["scope_claims"] is empty.  Called at the
end of handle_mode_cleared() and on failure paths in handle_mode_activated().

Tests in this module:
  1. test_natural_deactivation_no_b3_warning
       Normal /mode off → overlay gone → no B3 warning on next request.
  2. test_failed_activation_no_b3_warning
       Activation that fails mid-apply → overlay gone → no B3 warning.
  3. test_genuine_anomaly_still_warns
       Manual injection of overlay (direct session_state manipulation) must
       still fire the B3 warning (genuine anomaly path unchanged).
  4. test_mode_to_mode_transition_overlay_present_while_new_scope_active
       After clearing mode A and activating mode B, the overlay is present
       while B is active (refcount coherence preserved).
  5. test_overlay_discarded_after_final_mode_cleared
       After the last mode is cleared the overlay is removed and no B3
       warning fires.
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

# ---------------------------------------------------------------------------
# Module-level paths
# ---------------------------------------------------------------------------

BUNDLE_ROOT: Path = Path(__file__).resolve().parents[3]
MODES_DIR: Path = BUNDLE_ROOT / "modes"          # real bundle modes (mode-design.md lives here)
FIXTURES_DIR: Path = Path(__file__).resolve().parent / "fixtures"


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _make_coordinator(
    active_mode: str | None = None,
    agents: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a coordinator mock with the surface area the overlay and hooks need."""
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
# Test 1 — Natural deactivation must not trigger the B3 guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_natural_deactivation_no_b3_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After a normal in-process /mode off, no B3 warning fires on the next request.

    Sequence:
    1. Activate a mode that has contributes (creates a real RuntimeOverlay).
    2. Deactivate via handle_mode_cleared.
    3. Assert overlay is removed from session_state.
    4. Assert handle_provider_request does NOT emit the B3 warning.
    """
    coord = _make_coordinator(agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    # --- activate ---
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    # Overlay must be present after a mode with contributes is activated
    assert coord.session_state.get("mode_runtime_overlay") is not None, (
        "Setup failure: mode_runtime_overlay must exist after activation"
    )

    # --- deactivate (/mode off) ---
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_cleared("mode:cleared", {"name": "mode-design"})

    # KEY: overlay must be gone now
    assert coord.session_state.get("mode_runtime_overlay") is None, (
        "mode_runtime_overlay must be removed from session_state after a normal "
        "/mode off with no remaining scope contributions.  "
        "Fix: _discard_overlay_if_empty() must be called in handle_mode_cleared()."
    )

    # KEY: B3 warning must NOT fire on next provider request
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        result = await hooks.handle_provider_request("provider:request", {})

    assert result.action == "inject_context"
    assert 'source="mode-status"' in result.context_injection

    b3_warnings = [
        r
        for r in caplog.records
        if "active_mode is None" in r.message and r.levelno == logging.WARNING
    ]
    assert not b3_warnings, (
        "B3 guard must NOT fire after a normal in-process /mode off.  "
        "This is the false-positive that Option A fixes.  "
        f"Unexpected warnings: {[r.message for r in b3_warnings]}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Failed activation must not trigger the B3 guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_activation_no_b3_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After a failed activation the overlay is cleaned up; no B3 warning fires.

    A mode that fails mid-apply leaves active_mode=None and an empty overlay
    (after rollback).  The fix must discard that empty overlay so the B3 guard
    does not fire on subsequent requests.
    """
    # Build a mode that fails partway through overlay.apply() due to a
    # broken contributes entry — mirrors test_contribution_failure_rollback.
    bad_mode_dir = tmp_path / "bad-modes"
    bad_mode_dir.mkdir()
    (bad_mode_dir / "failing-mode.md").write_text(
        textwrap.dedent("""\
            ---
            mode:
              name: failing-mode
              description: A mode that fails to activate
              shortcut: false
              advertised: false
              default_action: block
              tools:
                safe: [mode]
              contributes:
                agents:
                  mode-author:
                    source: "@modes:agents/mode-author"
                  this-does-not-exist: "@modes:agents/this-does-not-exist"
            ---
            Broken on purpose.
        """),
        encoding="utf-8",
    )

    coord = _make_coordinator(agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR, bad_mode_dir])
    hooks = ModeHooks(coord, discovery)

    # Attempt activation — expected to fail
    coord.session_state["active_mode"] = "failing-mode"
    await hooks.handle_mode_activated("mode:activated", {"mode": "failing-mode"})

    # Sanity: active_mode must be cleared after a failed activation
    assert coord.session_state.get("active_mode") in (None, ""), (
        "Prerequisite: failed activation must clear active_mode"
    )

    # KEY: overlay must be gone after failed activation
    assert coord.session_state.get("mode_runtime_overlay") is None, (
        "mode_runtime_overlay must be removed from session_state after a failed "
        "activation (overlay was created but rolled back; it is now empty).  "
        "Fix: _discard_overlay_if_empty() must be called on the failure paths "
        "in handle_mode_activated()."
    )

    # KEY: B3 warning must NOT fire on next provider request
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        await hooks.handle_provider_request("provider:request", {})

    b3_warnings = [
        r
        for r in caplog.records
        if "active_mode is None" in r.message and r.levelno == logging.WARNING
    ]
    assert not b3_warnings, (
        "B3 guard must NOT fire after a failed activation.  "
        f"Unexpected warnings: {[r.message for r in b3_warnings]}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Genuine anomaly (direct injection) still warns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_genuine_anomaly_still_warns(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """Directly injecting an overlay into session_state still triggers the B3 warning.

    This is the test from TestB3SessionStateInconsistencyGuard —
    reproduced here to confirm Option A does not silence genuine anomalies.

    The manually injected MagicMock overlay has a truthy dump_state()["scope_claims"]
    (MagicMock returns truthy values by default), so _discard_overlay_if_empty()
    would NOT remove it — the B3 guard fires as expected.
    """
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    # Write a minimal mode file so discovery is happy
    (modes_dir / "design.md").write_text(
        textwrap.dedent("""\
            ---
            mode:
              name: design
              description: "design mode"
              tools:
                safe: [read_file]
              default_action: block
            ---
            # Design Mode
            You are in design mode.
        """),
        encoding="utf-8",
    )

    coord = _make_coordinator(active_mode=None)
    # Directly inject a MagicMock overlay — simulates a genuine session-resume
    # anomaly where the overlay object outlived the process restart state.
    coord.session_state["mode_runtime_overlay"] = MagicMock()

    discovery = ModeDiscovery(search_paths=[modes_dir])
    hooks = ModeHooks(coord, discovery)

    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        result = await hooks.handle_provider_request("provider:request", {})

    assert result.action == "inject_context"
    assert 'source="mode-status"' in result.context_injection

    assert any(
        "active_mode is None" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    ), (
        "B3 guard MUST still fire when an overlay is directly injected into "
        "session_state (genuine anomaly — e.g. real session-resume state loss).  "
        f"Logged messages: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# Test 4 — mode→mode transition: overlay present while new scope is active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_to_mode_transition_overlay_present_while_new_scope_active() -> None:
    """After switching modes, the overlay is present while the new mode is active.

    Sequence:
    1. Activate mode-design (contributes mode-author).
    2. Clear mode-design (overlay may become empty and get discarded).
    3. Activate test-overlap-mode (also contributes mode-author).
    4. Assert overlay is present (re-created for the new scope).

    This test guards the Option A invariant: removing an empty overlay on
    deactivation must not break the next activation.
    """
    coord = _make_coordinator(agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR, FIXTURES_DIR])
    hooks = ModeHooks(coord, discovery)

    # Step 1: activate mode-design
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})
    assert coord.session_state.get("mode_runtime_overlay") is not None, (
        "Overlay must be present after mode-design activation"
    )

    # Step 2: clear mode-design
    coord.session_state["active_mode"] = None
    await hooks.handle_mode_cleared("mode:cleared", {"name": "mode-design"})

    # Step 3: activate test-overlap-mode
    coord.session_state["active_mode"] = "test-overlap-mode"
    await hooks.handle_mode_activated("mode:activated", {"mode": "test-overlap-mode"})

    # Step 4: overlay must be present (re-created for test-overlap-mode scope)
    assert coord.session_state.get("mode_runtime_overlay") is not None, (
        "Overlay must be present after test-overlap-mode activation.  "
        "_get_or_create_overlay() creates a fresh one when the previous was discarded."
    )


# ---------------------------------------------------------------------------
# Test 5 — overlay discarded and no B3 warning after final mode cleared
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overlay_discarded_after_final_mode_cleared(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Full activate→clear cycle: overlay gone afterwards, no B3 warning on next request.

    End-to-end guard: verifies BOTH that the overlay is removed AND that the
    B3 warning is silenced across a full session lifecycle.
    """
    coord = _make_coordinator(agents={})
    discovery = ModeDiscovery(search_paths=[MODES_DIR])
    hooks = ModeHooks(coord, discovery)

    # Full cycle
    coord.session_state["active_mode"] = "mode-design"
    await hooks.handle_mode_activated("mode:activated", {"mode": "mode-design"})

    coord.session_state["active_mode"] = None
    await hooks.handle_mode_cleared("mode:cleared", {"name": "mode-design"})

    # No overlay in session_state
    assert coord.session_state.get("mode_runtime_overlay") is None, (
        "Overlay must be absent after the final mode is cleared"
    )

    # Multiple subsequent provider requests — none should trigger B3
    with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
        await hooks.handle_provider_request("provider:request", {})
        await hooks.handle_provider_request("provider:request", {})
        await hooks.handle_provider_request("provider:request", {})

    b3_warnings = [
        r
        for r in caplog.records
        if "active_mode is None" in r.message and r.levelno == logging.WARNING
    ]
    assert not b3_warnings, (
        "B3 guard must NOT fire on any subsequent provider request after the "
        "mode was properly deactivated.  "
        f"Got {len(b3_warnings)} spurious warning(s): "
        f"{[r.message for r in b3_warnings]}"
    )
