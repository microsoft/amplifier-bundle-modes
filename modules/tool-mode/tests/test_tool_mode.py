"""Tests for tool-mode module."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
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
              description: "{description or name + ' mode'}"
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


def _make_coordinator(
    tmp_path: Path,
    mode_names: list[str] | None = None,
    active_mode: str | None = None,
) -> MagicMock:
    """Create a mock coordinator with mode_discovery and mode_hooks in session_state."""
    from amplifier_module_hooks_mode import ModeDiscovery

    modes_dir = tmp_path / "modes"
    modes_dir.mkdir(exist_ok=True)
    for name in mode_names or []:
        _create_mode_file(modes_dir, name, f"{name} mode")

    discovery = ModeDiscovery(search_paths=[modes_dir])

    hooks = MagicMock()
    hooks.reset_warnings = MagicMock()

    coordinator = MagicMock()
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

        coordinator = _make_coordinator(
            tmp_path, ["plan"], active_mode="plan"
        )
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
        assert result.error["code"] == "mode_not_found"

    @pytest.mark.asyncio
    async def test_set_missing_name_rejected(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "set"})
        assert result.success is False
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
    async def test_set_confirm_policy_always_denies(
        self, tmp_path: Path
    ) -> None:
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

        coordinator = _make_coordinator(
            tmp_path, ["plan"], active_mode="plan"
        )
        tool = ModeTool(config={"gate_policy": "auto"}, coordinator=coordinator)

        result = await tool.execute({"operation": "clear"})
        assert result.success is True
        assert result.output["status"] == "cleared"
        assert coordinator.session_state["active_mode"] is None

    @pytest.mark.asyncio
    async def test_clear_resets_warnings(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(
            tmp_path, ["plan"], active_mode="plan"
        )
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

        # Clear
        await tool.execute({"operation": "clear"})

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
        assert result.error["code"] == "invalid_operation"

    @pytest.mark.asyncio
    async def test_missing_operation(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = _make_coordinator(tmp_path, ["plan"])
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({})
        assert result.success is False
        assert result.error["code"] == "invalid_operation"

    @pytest.mark.asyncio
    async def test_hooks_mode_not_mounted(self, tmp_path: Path) -> None:
        from amplifier_module_tool_mode import ModeTool

        coordinator = MagicMock()
        coordinator.session_state = {}  # No mode_discovery
        tool = ModeTool(config={}, coordinator=coordinator)

        result = await tool.execute({"operation": "list"})
        assert result.success is False
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
