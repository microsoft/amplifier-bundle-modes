"""Tests for ModeHooks and mount() behavior."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks


def _create_mode_file(path: Path, name: str, description: str = "") -> Path:
    """Helper: create a minimal mode .md file with valid YAML frontmatter."""
    mode_file = path / f"{name}.md"
    mode_file.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{description or name + " mode"}"
              tools:
                safe: [read_file, grep]
              default_action: block
            ---
            # {name.title()} Mode
            You are in {name} mode.
        """),
        encoding="utf-8",
    )
    return mode_file


def _make_coordinator(active_mode: str | None = None) -> MagicMock:
    """Create a mock coordinator with session_state."""
    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }
    coordinator.hooks = MagicMock()
    coordinator.get_capability = MagicMock(return_value=None)
    return coordinator


class TestMountEventRegistration:
    """Fix 1: mount() must register context injection on provider:request."""

    @pytest.mark.asyncio
    async def test_mount_registers_on_provider_request(self, tmp_path: Path) -> None:
        """The context injection handler must be registered on 'provider:request',
        NOT 'prompt:submit'."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")

        coordinator = _make_coordinator()

        from amplifier_module_hooks_mode import mount

        await mount(coordinator, {"search_paths": [str(modes_dir)]})

        register_calls = coordinator.hooks.register.call_args_list

        context_registration = None
        for c in register_calls:
            args, kwargs = c
            if kwargs.get("name") == "mode-context":
                context_registration = c
                break

        assert context_registration is not None, (
            "Expected a hooks.register call with name='mode-context'"
        )

        args, kwargs = context_registration
        event_name = args[0]
        assert event_name == "provider:request", (
            f"mode-context handler must be registered on 'provider:request', "
            f"but was registered on '{event_name}'"
        )


class TestHandlerMethodName:
    """Fix 1: The handler method should be named handle_provider_request."""

    def test_mode_hooks_has_handle_provider_request(self) -> None:
        """ModeHooks must have handle_provider_request method."""
        assert hasattr(ModeHooks, "handle_provider_request"), (
            "ModeHooks must have a 'handle_provider_request' method"
        )

    def test_mode_hooks_no_handle_prompt_submit(self) -> None:
        """The old handle_prompt_submit method must not exist."""
        assert not hasattr(ModeHooks, "handle_prompt_submit"), (
            "ModeHooks must NOT have the old 'handle_prompt_submit' method -- "
            "it should be renamed to 'handle_provider_request'"
        )


class TestInfrastructureToolsBypass:
    """Fix 2: Infrastructure tools must bypass the mode tool cascade."""

    @pytest.mark.asyncio
    async def test_mode_tool_allowed_by_default(self, tmp_path: Path) -> None:
        """The 'mode' tool must be allowed even when default_action is 'block'
        and 'mode' is not in safe_tools."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "strict")

        coordinator = _make_coordinator(active_mode="strict")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "mode"})
        assert result.action == "continue", (
            f"'mode' tool must be allowed (infrastructure tool), "
            f"but got action='{result.action}'"
        )

    @pytest.mark.asyncio
    async def test_todo_tool_allowed_by_default(self, tmp_path: Path) -> None:
        """The 'todo' tool must be allowed even when default_action is 'block'
        and 'todo' is not in safe_tools."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "notodo")

        coordinator = _make_coordinator(active_mode="notodo")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "todo"})
        assert result.action == "continue", (
            f"'todo' tool must be allowed (infrastructure tool), "
            f"but got action='{result.action}'"
        )

    @pytest.mark.asyncio
    async def test_non_infrastructure_tool_still_blocked(self, tmp_path: Path) -> None:
        """Tools NOT in infrastructure_tools must still follow the cascade."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "strict")

        coordinator = _make_coordinator(active_mode="strict")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "write_file"})
        assert result.action == "deny", (
            f"'write_file' must still be blocked by default_action, "
            f"but got action='{result.action}'"
        )


class TestInfrastructureToolsConfig:
    """Fix 2: infrastructure_tools must be configurable."""

    @pytest.mark.asyncio
    async def test_custom_infrastructure_tools(self, tmp_path: Path) -> None:
        """When infrastructure_tools is set to a custom list, only those tools bypass."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "custom")

        coordinator = _make_coordinator(active_mode="custom")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery, infrastructure_tools={"mode"})

        # "mode" should still be allowed
        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "mode"})
        assert result.action == "continue"

        # "todo" should now be blocked (not in custom list)
        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "todo"})
        assert result.action == "deny"

    @pytest.mark.asyncio
    async def test_empty_infrastructure_tools_blocks_mode(self, tmp_path: Path) -> None:
        """When infrastructure_tools is empty, even the mode tool is blocked."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "locked")

        coordinator = _make_coordinator(active_mode="locked")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery, infrastructure_tools=set())

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "mode"})
        assert result.action == "deny", (
            "With empty infrastructure_tools, 'mode' must be blocked"
        )


class TestModeActiveSignal:
    """Fix 3: Context injection must include an explicit MODE ACTIVE banner."""

    @pytest.mark.asyncio
    async def test_context_has_mode_active_banner(self, tmp_path: Path) -> None:
        """Injected context must start with 'MODE ACTIVE: {name}' inside the tags."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        coordinator = _make_coordinator(active_mode="plan")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "inject_context"
        content = result.context_injection
        assert "MODE ACTIVE: plan" in content

    @pytest.mark.asyncio
    async def test_context_has_do_not_reactivate_warning(self, tmp_path: Path) -> None:
        """Injected context must warn the agent not to re-activate the current mode."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "brainstorm", "Brainstorm mode")

        coordinator = _make_coordinator(active_mode="brainstorm")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})
        content = result.context_injection
        assert "do NOT call" in content or "do not call" in content.lower()
        assert "brainstorm" in content

    @pytest.mark.asyncio
    async def test_context_still_contains_mode_content(self, tmp_path: Path) -> None:
        """The mode's markdown body must still be included after the banner."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        coordinator = _make_coordinator(active_mode="plan")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})
        content = result.context_injection
        assert "You are in plan mode." in content

    @pytest.mark.asyncio
    async def test_context_wrapped_in_system_reminder_tags(
        self, tmp_path: Path
    ) -> None:
        """Context must be wrapped in <system-reminder> tags with mode source."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        coordinator = _make_coordinator(active_mode="plan")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})
        content = result.context_injection
        assert content.startswith('<system-reminder source="mode-plan">')
        assert content.rstrip().endswith("</system-reminder>")
