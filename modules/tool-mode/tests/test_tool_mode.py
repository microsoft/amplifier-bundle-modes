"""Tests for tool-mode module."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _create_mode_file(path: Path, name: str, description: str = "") -> Path:
    """Create a minimal mode .md file."""
    mode_file = path / f"{name}.md"
    mode_file.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{description or name + " mode"}"
              tools:
                safe: [read_file, grep]
                warn: [bash]
              default_action: block
            ---
            # {name.title()} Mode
            You are in {name} mode.
        """),
        encoding="utf-8",
    )
    return mode_file


def _create_mode_file_with_transitions(
    path: Path,
    name: str,
    allowed_transitions: list[str] | None = None,
    description: str = "",
) -> Path:
    """Create a mode .md file with allowed_transitions set."""
    if allowed_transitions is not None:
        items = ", ".join(allowed_transitions)
        # 14 spaces matches the nesting level inside textwrap.dedent block (12 base + 2 indent)
        transitions_yaml = f"\n              allowed_transitions: [{items}]"
    else:
        transitions_yaml = ""
    mode_file = path / f"{name}.md"
    mode_file.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{description or name + " mode"}"
              tools:
                safe: [read_file, grep]
                warn: [bash]
              default_action: block{transitions_yaml}
            ---
            # {name.title()} Mode
            You are in {name} mode.
        """),
        encoding="utf-8",
    )
    return mode_file


def _make_coordinator(
    tmp_path: Path,
    mode_names: list[str] | None = None,
    active_mode: str | None = None,
) -> MagicMock:
    """Create a mock coordinator with mode_discovery and mode_hooks in session_state.

    coordinator.hooks.emit is an AsyncMock so that bare ``await coordinator.hooks.emit(...)``
    calls in the production code (which no longer wrap emits in per-emit try/except) work
    without raising ``TypeError: object MagicMock can't be used in 'await' expression``.
    """
    from amplifier_module_hooks_mode import ModeDiscovery

    modes_dir = tmp_path / "modes"
    modes_dir.mkdir(exist_ok=True)
    for name in mode_names or []:
        _create_mode_file(modes_dir, name, f"{name} mode")

    discovery = ModeDiscovery(search_paths=[modes_dir])

    hooks = MagicMock()
    hooks.reset_warnings = MagicMock()

    coordinator = MagicMock()
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "mode_discovery": discovery,
        "mode_hooks": hooks,
    }
    return coordinator


class TestModeToolList:
    """Tests for mode(operation='list')."""

    @pytest.mark.asyncio
    async def test_list_returns_available_modes(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan", "review"])
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({"operation": "list"})
        assert result.success is True
        names = [m["name"] for m in result.output["modes"]]
        assert "plan" in names
        assert "review" in names

    @pytest.mark.asyncio
    async def test_list_empty_when_no_modes(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, [])
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({"operation": "list"})
        assert result.success is True
        assert result.output["modes"] == []


class TestModeToolCurrent:
    """Tests for mode(operation='current')."""

    @pytest.mark.asyncio
    async def test_current_when_active(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode="plan")
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({"operation": "current"})
        assert result.success is True
        assert result.output["active_mode"] == "plan"
        assert "description" in result.output

    @pytest.mark.asyncio
    async def test_current_when_none(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode=None)
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({"operation": "current"})
        assert result.success is True
        assert result.output["active_mode"] is None


class TestModeToolSet:
    """Tests for mode(operation='set')."""

    @pytest.mark.asyncio
    async def test_set_auto_policy_activates_immediately(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan", "review"])
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "plan"})
        assert result.success is True
        assert result.output["status"] == "activated"
        assert result.output["mode"] == "plan"
        assert coordinator.session_state["active_mode"] == "plan"

    @pytest.mark.asyncio
    async def test_set_returns_tool_policies(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "plan"})
        assert result.success is True
        assert "safe_tools" in result.output
        assert "read_file" in result.output["safe_tools"]

    @pytest.mark.asyncio
    async def test_set_resets_warnings(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        await tool.execute({"operation": "set", "name": "plan"})
        coordinator.session_state["mode_hooks"].reset_warnings.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_invalid_mode_rejected(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "nonexistent"})
        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "mode_not_found"

    @pytest.mark.asyncio
    async def test_set_missing_name_rejected(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set"})
        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "missing_name"

    @pytest.mark.asyncio
    async def test_set_warn_policy_denies_first_allows_second(
        self, tmp_path: Path
    ) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={"gate_policy": "warn"}, coordinator=coordinator)

        # First call: denied with warning
        result1 = await tool.execute({"operation": "set", "name": "plan"})
        assert result1.success is False
        assert result1.output["status"] == "denied"
        assert "user_instruction" in result1.output
        assert coordinator.session_state["active_mode"] is None  # Not changed

        # Second call: allowed
        result2 = await tool.execute({"operation": "set", "name": "plan"})
        assert result2.success is True
        assert result2.output["status"] == "activated"
        assert coordinator.session_state["active_mode"] == "plan"

    @pytest.mark.asyncio
    async def test_set_warn_policy_resets_on_different_mode(
        self, tmp_path: Path
    ) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan", "review"])
        tool = ModeTool(config={"gate_policy": "warn"}, coordinator=coordinator)

        # Warn for plan
        result1 = await tool.execute({"operation": "set", "name": "plan"})
        assert result1.success is False

        # Now try review - should also warn (different mode)
        result2 = await tool.execute({"operation": "set", "name": "review"})
        assert result2.success is False
        assert result2.output["denied_mode"] == "review"

    @pytest.mark.asyncio
    async def test_set_confirm_policy_always_denies(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={"gate_policy": "confirm"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "plan"})
        assert result.success is False
        assert result.output["status"] == "denied"
        # Confirm policy should instruct user about /mode command
        assert "user_instruction" in result.output


class TestModeToolClear:
    """Tests for mode(operation='clear')."""

    @pytest.mark.asyncio
    async def test_clear_deactivates_mode(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})
        assert result.success is True
        assert result.output["status"] == "cleared"
        assert coordinator.session_state["active_mode"] is None

    @pytest.mark.asyncio
    async def test_clear_resets_warnings(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        await tool.execute({"operation": "clear"})
        coordinator.session_state["mode_hooks"].reset_warnings.assert_called()

    @pytest.mark.asyncio
    async def test_clear_when_no_mode_active(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode=None)
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})
        assert result.success is True
        assert result.output["status"] == "cleared"

    @pytest.mark.asyncio
    async def test_clear_resets_warn_gate_memory(self, tmp_path: Path) -> None:
        """After clearing, warn gate should require fresh confirmation."""
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={"gate_policy": "warn"}, coordinator=coordinator)

        # Warm up warn gate: first denied, second allowed
        await tool.execute({"operation": "set", "name": "plan"})  # denied
        await tool.execute({"operation": "set", "name": "plan"})  # allowed

        # Clear (warn gate: first denied, second allowed)
        await tool.execute({"operation": "clear"})  # denied (clear warn)
        await tool.execute({"operation": "clear"})  # allowed - actually clears

        # Now try again - should warn again (fresh start)
        result = await tool.execute({"operation": "set", "name": "plan"})
        assert result.success is False  # Denied again
        assert result.output["status"] == "denied"


class TestModeToolEdgeCases:
    """Edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_invalid_operation(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({"operation": "invalid"})
        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "invalid_operation"

    @pytest.mark.asyncio
    async def test_missing_operation(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "invalid_operation"

    @pytest.mark.asyncio
    async def test_hooks_mode_not_mounted(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = MagicMock()
        coordinator.session_state = {}  # No mode_discovery
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({"operation": "list"})
        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "hooks_mode_not_mounted"

    @pytest.mark.asyncio
    async def test_input_schema_is_valid(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, [])
        tool = ModeTool(config={}, coordinator=coordinator)

        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "operation" in schema["properties"]
        assert "name" in schema["properties"]
        assert "operation" in schema["required"]

    @pytest.mark.asyncio
    async def test_tool_name_and_description(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, [])
        tool = ModeTool(config={}, coordinator=coordinator)

        assert tool.name == "mode"
        assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_default_gate_policy_is_warn(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={}, coordinator=coordinator)
        assert tool.gate_policy == "warn"


class TestMount:
    """Tests for the mount() function."""

    @pytest.mark.asyncio
    async def test_mount_registers_tool(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import mount

        coordinator = _make_coordinator(tmp_path, ["plan"])
        coordinator.mount = AsyncMock()

        await mount(coordinator, config={"gate_policy": "auto"})

        coordinator.mount.assert_called_once()
        call_args = coordinator.mount.call_args
        assert call_args[0][0] == "tools"  # First positional: "tools"
        tool = call_args[0][1]  # Second positional: tool instance
        assert tool.name == "mode"
        assert tool.gate_policy == "auto"

    @pytest.mark.asyncio
    async def test_mount_default_config(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import mount

        coordinator = _make_coordinator(tmp_path, ["plan"])
        coordinator.mount = AsyncMock()

        await mount(coordinator)

        tool = coordinator.mount.call_args[0][1]
        assert tool.gate_policy == "warn"  # Default

    @pytest.mark.asyncio
    async def test_mount_warns_if_hooks_mode_missing(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import mount

        coordinator = MagicMock()
        coordinator.session_state = {}  # No mode_discovery
        coordinator.mount = AsyncMock()

        # Should not crash - just warn
        await mount(coordinator)
        coordinator.mount.assert_called_once()


def _create_mode_file_with_clear_policy(
    path: Path,
    name: str,
    allow_clear: bool = True,
    allowed_transitions: list[str] | None = None,
    description: str = "",
) -> Path:
    """Create a mode .md file with allow_clear and optional allowed_transitions set."""
    allow_clear_yaml = f"\n              allow_clear: {str(allow_clear).lower()}"
    if allowed_transitions is not None:
        items = ", ".join(allowed_transitions)
        transitions_yaml = f"\n              allowed_transitions: [{items}]"
    else:
        transitions_yaml = ""
    mode_file = path / f"{name}.md"
    mode_file.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{description or name + " mode"}"
              tools:
                safe: [read_file, grep]
                warn: [bash]
              default_action: block{allow_clear_yaml}{transitions_yaml}
            ---
            # {name.title()} Mode
            You are in {name} mode.
        """),
        encoding="utf-8",
    )
    return mode_file


def _make_coordinator_with_modes_dir(
    modes_dir: Path,
    active_mode: str | None = None,
) -> MagicMock:
    """Create a mock coordinator from an already-populated modes directory."""
    from amplifier_module_hooks_mode import ModeDiscovery

    discovery = ModeDiscovery(search_paths=[modes_dir])

    hooks = MagicMock()
    hooks.reset_warnings = MagicMock()

    coordinator = MagicMock()
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "mode_discovery": discovery,
        "mode_hooks": hooks,
    }
    return coordinator


class TestAllowedTransitions:
    """Tests for allowed_transitions enforcement in _handle_set."""

    @pytest.mark.asyncio
    async def test_allowed_transition_succeeds(self, tmp_path: Path) -> None:
        """When target mode is in allowed_transitions, transition should succeed."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(
            modes_dir, "plan", allowed_transitions=["review", "code"]
        )
        _create_mode_file(modes_dir, "review")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "review"})

        assert result.success is True
        assert result.output["status"] == "activated"
        assert result.output["mode"] == "review"

    @pytest.mark.asyncio
    async def test_denied_transition_returns_error(self, tmp_path: Path) -> None:
        """When target mode is NOT in allowed_transitions, return transition_denied error."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(
            modes_dir, "plan", allowed_transitions=["review"]
        )
        _create_mode_file(modes_dir, "code")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "code"})

        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "transition_denied"
        assert "plan" in result.error["message"]
        assert "code" in result.error["message"]
        assert coordinator.session_state["active_mode"] == "plan"  # Unchanged

    @pytest.mark.asyncio
    async def test_no_allowed_transitions_allows_any(self, tmp_path: Path) -> None:
        """When allowed_transitions is None (absent), any transition is allowed."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")  # No allowed_transitions field
        _create_mode_file(modes_dir, "review")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "review"})

        assert result.success is True
        assert result.output["status"] == "activated"

    @pytest.mark.asyncio
    async def test_transition_check_before_gate_policy(self, tmp_path: Path) -> None:
        """Denied transitions get hard error even with warn gate policy."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(
            modes_dir, "plan", allowed_transitions=["review"]
        )
        _create_mode_file(modes_dir, "code")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "warn"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "code"})

        # Should get a hard error (result.error), not a warn "denied" in result.output
        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "transition_denied"

    @pytest.mark.asyncio
    async def test_no_active_mode_allows_any(self, tmp_path: Path) -> None:
        """When no mode is active, any mode can be set (no current restrictions)."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(
            modes_dir, "plan", allowed_transitions=["review"]
        )
        _create_mode_file(modes_dir, "code")  # NOT in plan's allowed list

        # active_mode=None → no current mode to enforce transitions from
        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode=None)
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "code"})

        assert result.success is True
        assert result.output["status"] == "activated"

    @pytest.mark.asyncio
    async def test_empty_allowed_transitions_locks_mode(self, tmp_path: Path) -> None:
        """When allowed_transitions is [] (empty list), no transitions are possible."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(modes_dir, "plan", allowed_transitions=[])
        _create_mode_file(modes_dir, "review")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "review"})

        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "transition_denied"
        assert "(none)" in result.error["message"]


class TestModeToolClearEnforcement:
    """Tests for allow_clear enforcement and gate policy in _handle_clear."""

    @pytest.mark.asyncio
    async def test_clear_denied_when_allow_clear_false(self, tmp_path: Path) -> None:
        """Clear is denied when current mode has allow_clear: false."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_clear_policy(
            modes_dir, "plan", allow_clear=False, allowed_transitions=["review"]
        )
        _create_mode_file(modes_dir, "review")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})

        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "clear_denied"
        assert "plan" in result.error["message"]
        assert "review" in result.error["message"]  # allowed transitions mentioned
        assert coordinator.session_state["active_mode"] == "plan"  # Unchanged

    @pytest.mark.asyncio
    async def test_clear_allowed_when_allow_clear_true(self, tmp_path: Path) -> None:
        """Clear succeeds when current mode has allow_clear: true."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_clear_policy(modes_dir, "plan", allow_clear=True)

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})

        assert result.success is True
        assert result.output["status"] == "cleared"
        assert coordinator.session_state["active_mode"] is None

    @pytest.mark.asyncio
    async def test_clear_allowed_when_allow_clear_absent(self, tmp_path: Path) -> None:
        """Clear succeeds when mode file has no allow_clear field (backward compat)."""
        from amplifier_module_tool_mode import ModeTool

        # Use original _make_coordinator which creates modes without allow_clear field
        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})

        assert result.success is True
        assert result.output["status"] == "cleared"

    @pytest.mark.asyncio
    async def test_warn_policy_first_clear_denied_second_succeeds(
        self, tmp_path: Path
    ) -> None:
        """With warn gate, first clear is denied with instruction, second succeeds."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_clear_policy(modes_dir, "plan", allow_clear=True)

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "warn"}, coordinator=coordinator)

        # First clear: denied (warn gate)
        result1 = await tool.execute({"operation": "clear"})
        assert result1.success is False
        assert result1.output["status"] == "denied"
        assert "user_instruction" in result1.output
        assert coordinator.session_state["active_mode"] == "plan"  # Unchanged

        # Second clear: allowed (warn gate passed)
        result2 = await tool.execute({"operation": "clear"})
        assert result2.success is True
        assert result2.output["status"] == "cleared"
        assert coordinator.session_state["active_mode"] is None

    @pytest.mark.asyncio
    async def test_confirm_policy_clear_always_denied(self, tmp_path: Path) -> None:
        """With confirm gate, clear is always denied."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_clear_policy(modes_dir, "plan", allow_clear=True)

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "confirm"}, coordinator=coordinator)

        result1 = await tool.execute({"operation": "clear"})
        assert result1.success is False
        assert result1.output["status"] == "denied"
        assert "user_instruction" in result1.output

        result2 = await tool.execute({"operation": "clear"})
        assert result2.success is False
        assert result2.output["status"] == "denied"

    @pytest.mark.asyncio
    async def test_allow_clear_false_takes_precedence_over_auto_gate(
        self, tmp_path: Path
    ) -> None:
        """allow_clear: false always denies, even with auto gate policy."""
        from amplifier_module_tool_mode import ModeTool

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_clear_policy(modes_dir, "plan", allow_clear=False)

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})

        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "clear_denied"
        assert coordinator.session_state["active_mode"] == "plan"  # Unchanged


class TestActivatedAndChangedEvents:
    """Tests for mode:activated and mode:changed event emission from _activate_mode."""

    @pytest.mark.asyncio
    async def test_off_to_on_emits_mode_activated(self, tmp_path: Path) -> None:
        """Off→on: exactly one mode:activated emitted with all required keys; no mode:changed."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_ACTIVATED, MODE_CHANGED

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode=None)
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "plan"})

        assert result.success is True
        emit_calls = coordinator.hooks.emit.call_args_list
        activated_calls = [c for c in emit_calls if c.args[0] == MODE_ACTIVATED]
        changed_calls = [c for c in emit_calls if c.args[0] == MODE_CHANGED]

        assert len(activated_calls) == 1, "expected exactly one mode:activated call"
        assert len(changed_calls) == 0, "expected no mode:changed calls"

        payload = activated_calls[0].args[1]
        assert payload["mode"] == "plan"
        assert "description" in payload
        assert "default_action" in payload
        assert "safe_tools" in payload
        assert "warn_tools" in payload
        assert "confirm_tools" in payload
        assert "block_tools" in payload

    @pytest.mark.asyncio
    async def test_on_to_on_emits_mode_changed(self, tmp_path: Path) -> None:
        """On→on: exactly one mode:changed emitted with from_mode/to_mode; no 'mode' key; no mode:activated."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_ACTIVATED, MODE_CHANGED

        coordinator = _make_coordinator(
            tmp_path, ["plan", "review"], active_mode="plan"
        )
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "review"})

        assert result.success is True
        emit_calls = coordinator.hooks.emit.call_args_list
        activated_calls = [c for c in emit_calls if c.args[0] == MODE_ACTIVATED]
        changed_calls = [c for c in emit_calls if c.args[0] == MODE_CHANGED]

        assert len(changed_calls) == 1, "expected exactly one mode:changed call"
        assert len(activated_calls) == 0, "expected no mode:activated calls"

        payload = changed_calls[0].args[1]
        assert payload["from_mode"] == "plan"
        assert payload["to_mode"] == "review"
        assert "mode" not in payload, (
            "'mode' key must not appear in mode:changed payload"
        )

    @pytest.mark.asyncio
    async def test_activated_and_changed_are_mutually_exclusive(
        self, tmp_path: Path
    ) -> None:
        """Exactly one of mode:activated or mode:changed fires per activation, never both."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_ACTIVATED, MODE_CHANGED

        coordinator = _make_coordinator(tmp_path, ["plan", "review"], active_mode=None)
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        # First activation: None → plan
        await tool.execute({"operation": "set", "name": "plan"})
        first_calls = [
            c
            for c in coordinator.hooks.emit.call_args_list
            if c.args[0] in (MODE_ACTIVATED, MODE_CHANGED)
        ]
        assert len(first_calls) == 1, "None→plan must emit exactly one mode event"

        # Second activation: plan → review
        coordinator.hooks.emit.reset_mock()
        await tool.execute({"operation": "set", "name": "review"})
        second_calls = [
            c
            for c in coordinator.hooks.emit.call_args_list
            if c.args[0] in (MODE_ACTIVATED, MODE_CHANGED)
        ]
        assert len(second_calls) == 1, "plan→review must emit exactly one mode event"

    @pytest.mark.asyncio
    async def test_activate_mode_is_async(self, tmp_path: Path) -> None:
        """_activate_mode must be a coroutine function (declared with async def)."""
        import inspect

        from amplifier_module_tool_mode import ModeTool

        assert inspect.iscoroutinefunction(ModeTool._activate_mode), (
            "_activate_mode must be declared with 'async def'"
        )

    @pytest.mark.asyncio
    async def test_emit_failure_causes_activation_to_fail_with_internal_error(
        self, tmp_path: Path
    ) -> None:
        """If emit raises, activation fails and session_state is NOT updated.

        The emit-before-state-change pattern means a bridge/serialization error
        causes the outer try/except to return internal_error. Since state is only
        mutated AFTER the emit succeeds, the observable state stays consistent with
        the ToolResult: both report failure.
        """
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode=None)
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock(side_effect=RuntimeError("emit failure"))
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "plan"})

        assert result.success is False
        assert result.error is not None
        assert result.error.get("code") == "internal_error"
        # State must NOT be changed — emit failed before state mutation
        assert coordinator.session_state["active_mode"] is None


class TestClearedEvent:
    """Tests for mode:cleared event emission from _handle_clear."""

    @pytest.mark.asyncio
    async def test_clear_active_mode_emits_mode_cleared(self, tmp_path: Path) -> None:
        """Clear when active_mode='plan' emits exactly one mode:cleared with correct payload."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_CLEARED

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode="plan")
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})

        assert result.success is True
        emit_calls = coordinator.hooks.emit.call_args_list
        cleared_calls = [c for c in emit_calls if c.args[0] == MODE_CLEARED]

        assert len(cleared_calls) == 1, "expected exactly one mode:cleared call"
        payload = cleared_calls[0].args[1]
        assert payload == {"previous_mode": "plan"}

    @pytest.mark.asyncio
    async def test_clear_no_active_mode_does_not_emit_mode_cleared(
        self, tmp_path: Path
    ) -> None:
        """Clear when active_mode=None emits no mode:cleared (previous is None guard)."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_CLEARED

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode=None)
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})

        assert result.success is True
        emit_calls = coordinator.hooks.emit.call_args_list
        cleared_calls = [c for c in emit_calls if c.args[0] == MODE_CLEARED]

        assert len(cleared_calls) == 0, (
            "expected no mode:cleared when no mode was active"
        )

    @pytest.mark.asyncio
    async def test_emit_failure_causes_clear_to_fail_with_internal_error(
        self, tmp_path: Path
    ) -> None:
        """If emit raises, clear fails and active_mode is NOT changed.

        The emit-before-state-change pattern means a bridge/serialization error
        causes the outer try/except to return internal_error. Since state is only
        mutated AFTER the emit succeeds, the observable state stays consistent with
        the ToolResult: both report failure.
        """
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"], active_mode="plan")
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock(side_effect=RuntimeError("emit failure"))
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})

        assert result.success is False
        assert result.error is not None
        assert result.error.get("code") == "internal_error"
        # State must NOT be changed — emit failed before state mutation
        assert coordinator.session_state["active_mode"] == "plan"


class TestTransitionDeniedAndActivationGatedEvents:
    """Tests for mode:transition_denied and mode:activation_gated event emission."""

    @pytest.mark.asyncio
    async def test_transition_denied_emits_event(self, tmp_path: Path) -> None:
        """From 'plan' (allowed=['review']) to 'code': error code=transition_denied and
        exactly one mode:transition_denied emitted with correct payload."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_TRANSITION_DENIED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(
            modes_dir, "plan", allowed_transitions=["review"]
        )
        _create_mode_file_with_transitions(modes_dir, "code")
        _create_mode_file_with_transitions(modes_dir, "review")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "code"})

        assert result.success is False
        assert result.error is not None
        assert result.error["code"] == "transition_denied"

        emit_calls = coordinator.hooks.emit.call_args_list
        denied_calls = [c for c in emit_calls if c.args[0] == MODE_TRANSITION_DENIED]
        assert len(denied_calls) == 1, (
            "expected exactly one mode:transition_denied call"
        )

        payload = denied_calls[0].args[1]
        assert payload == {
            "from_mode": "plan",
            "to_mode": "code",
            "allowed_transitions": ["review"],
        }

    @pytest.mark.asyncio
    async def test_gate_policy_warn_from_off_emits_activation_gated(
        self, tmp_path: Path
    ) -> None:
        """gate_policy='warn' from active_mode=None: emits one mode:activation_gated
        with gate_policy='warn', target_mode='plan', description present, from_mode=None."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_ACTIVATION_GATED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(
            modes_dir, "plan", description="Plan mode desc"
        )

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode=None)
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "warn"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "plan"})

        assert result.success is False
        assert result.output["status"] == "denied"

        emit_calls = coordinator.hooks.emit.call_args_list
        gated_calls = [c for c in emit_calls if c.args[0] == MODE_ACTIVATION_GATED]
        assert len(gated_calls) == 1, "expected exactly one mode:activation_gated call"

        payload = gated_calls[0].args[1]
        assert payload["gate_policy"] == "warn"
        assert payload["target_mode"] == "plan"
        assert payload["description"]  # non-empty
        assert payload["from_mode"] is None

    @pytest.mark.asyncio
    async def test_gate_policy_confirm_from_active_mode_emits_activation_gated(
        self, tmp_path: Path
    ) -> None:
        """gate_policy='confirm' from active_mode='plan': emits mode:activation_gated
        with from_mode='plan'."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_ACTIVATION_GATED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(modes_dir, "plan")
        _create_mode_file_with_transitions(modes_dir, "code")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode="plan")
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "confirm"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "code"})

        assert result.success is False
        assert result.output["status"] == "denied"

        emit_calls = coordinator.hooks.emit.call_args_list
        gated_calls = [c for c in emit_calls if c.args[0] == MODE_ACTIVATION_GATED]
        assert len(gated_calls) == 1, "expected exactly one mode:activation_gated call"

        payload = gated_calls[0].args[1]
        assert payload["gate_policy"] == "confirm"
        assert payload["target_mode"] == "code"
        assert payload["from_mode"] == "plan"

    @pytest.mark.asyncio
    async def test_gate_policy_auto_emits_no_activation_gated(
        self, tmp_path: Path
    ) -> None:
        """gate_policy='auto' activates immediately without emitting mode:activation_gated."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_ACTIVATION_GATED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(modes_dir, "plan")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode=None)
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set", "name": "plan"})

        assert result.success is True
        assert result.output["status"] == "activated"

        emit_calls = coordinator.hooks.emit.call_args_list
        gated_calls = [c for c in emit_calls if c.args[0] == MODE_ACTIVATION_GATED]
        assert len(gated_calls) == 0, (
            "expected no mode:activation_gated for auto policy"
        )

    @pytest.mark.asyncio
    async def test_warn_retry_emits_gated_once_then_no_more(
        self, tmp_path: Path
    ) -> None:
        """Warn-retry sequence: first call emits activation_gated (total=1),
        second call activates without additional activation_gated (still total=1)."""
        from unittest.mock import AsyncMock

        from amplifier_module_tool_mode import ModeTool
        from amplifier_module_tool_mode.events import MODE_ACTIVATION_GATED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file_with_transitions(modes_dir, "plan")

        coordinator = _make_coordinator_with_modes_dir(modes_dir, active_mode=None)
        coordinator.hooks = MagicMock()
        coordinator.hooks.emit = AsyncMock()
        tool = ModeTool(config={"gate_policy": "warn"}, coordinator=coordinator)

        # First call: denied with gate
        result1 = await tool.execute({"operation": "set", "name": "plan"})
        assert result1.success is False

        gated_calls_after_first = [
            c
            for c in coordinator.hooks.emit.call_args_list
            if c.args[0] == MODE_ACTIVATION_GATED
        ]
        assert len(gated_calls_after_first) == 1, (
            "expected exactly one mode:activation_gated after first call"
        )

        # Second call: activated (warn retry)
        result2 = await tool.execute({"operation": "set", "name": "plan"})
        assert result2.success is True
        assert result2.output["status"] == "activated"

        gated_calls_total = [
            c
            for c in coordinator.hooks.emit.call_args_list
            if c.args[0] == MODE_ACTIVATION_GATED
        ]
        assert len(gated_calls_total) == 1, (
            "expected no additional mode:activation_gated on retry activation"
        )


class TestEventsContributorRegistration:
    """Tests for observability.events contributor registration in mount()."""

    @pytest.mark.asyncio
    async def test_mount_registers_observability_events_contributor(
        self, tmp_path: Path
    ) -> None:
        from amplifier_module_tool_mode import mount
        from amplifier_module_tool_mode.events import ALL_EVENTS

        coordinator = MagicMock()
        coordinator.session_state = {}
        coordinator.mount = AsyncMock()
        coordinator.register_contributor = MagicMock()

        await mount(coordinator, config={"gate_policy": "auto"})

        # Find the register_contributor call for 'observability.events'
        obs_call = None
        for call in coordinator.register_contributor.call_args_list:
            if call.args[0] == "observability.events":
                obs_call = call
                break

        assert obs_call is not None, (
            "Expected register_contributor to be called with 'observability.events'"
        )
        contributor_id = obs_call.args[1]
        supplier = obs_call.args[2]
        assert contributor_id == "bundle-modes:tool-mode"
        assert supplier() == ALL_EVENTS
