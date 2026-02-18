"""Tests for ModeHooks and mount() behavior."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from amplifier_module_hooks_mode import ModeHooks


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
