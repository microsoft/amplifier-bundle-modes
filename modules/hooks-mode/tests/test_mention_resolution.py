"""Tests for @-mention resolution in handle_provider_request().

Verifies that @namespace:path lines in mode body content are resolved to
actual file content before injection, matching the behavior of load_mentions()
in the foundation bundle layer for agent .md bodies.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks


def _create_mode_file(
    path: Path,
    name: str,
    body: str | None = None,
    description: str = "",
) -> Path:
    """Helper: create a mode .md file with optional custom body."""
    mode_file = path / f"{name}.md"
    if body is None:
        body = f"# {name.title()} Mode\nYou are in {name} mode."
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
            """)
        + body
        + "\n",
        encoding="utf-8",
    )
    return mode_file


def _make_coordinator(active_mode: str | None = None) -> MagicMock:
    """Create a mock coordinator with session_state."""
    from unittest.mock import AsyncMock

    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.get_capability = MagicMock(return_value=None)
    return coordinator


class TestMentionResolution:
    """handle_provider_request() must resolve @-mentions in mode body content."""

    @pytest.mark.asyncio
    async def test_at_mention_resolved_to_file_content(self, tmp_path: Path) -> None:
        """An @namespace:path line in the mode body must be replaced with the file's content."""
        # Create the file that the @-mention will point to
        context_file = tmp_path / "debugging-techniques.md"
        context_file.write_text(
            "## Debugging Techniques\nAlways check the logs first.",
            encoding="utf-8",
        )

        # Create a mode file whose body contains an @-mention on its own line
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(
            modes_dir,
            "debug",
            body="# Debug Mode\n@superpowers:context/debugging-techniques.md",
        )

        # Set up coordinator with a mention_resolver that resolves the mention
        coordinator = _make_coordinator(active_mode="debug")
        resolver = MagicMock()
        resolver.resolve = MagicMock(return_value=str(context_file))
        coordinator.get_capability = MagicMock(
            side_effect=lambda key: resolver if key == "mention_resolver" else None
        )

        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "inject_context", (
            f"Expected inject_context action, got {result.action!r}"
        )
        content = result.context_injection
        assert content is not None, (
            "context_injection should not be None when action is inject_context"
        )
        assert "Always check the logs first." in content, (
            "@-mention should have been replaced with file content, "
            f"but injected context was:\n{content}"
        )
        assert "@superpowers:context/debugging-techniques.md" not in content, (
            "Raw @-mention text must not appear in the injected context after resolution"
        )

    @pytest.mark.asyncio
    async def test_mode_without_mentions_unchanged(self, tmp_path: Path) -> None:
        """Mode body without @-mentions must work exactly as before (no resolver queried)."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(
            modes_dir,
            "plan",
            body="# Plan Mode\nThink before you act.",
        )

        coordinator = _make_coordinator(active_mode="plan")
        # Discovery is created without a coordinator so no bundle discovery is triggered
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "inject_context"
        content = result.context_injection
        assert content is not None, (
            "context_injection should not be None when action is inject_context"
        )
        assert "Think before you act." in content, (
            "Mode body content must be injected unchanged when there are no @-mentions"
        )
        # When there are no @-mentions, get_capability must never be called —
        # the early-return optimisation avoids touching the resolver entirely
        coordinator.get_capability.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_mention_graceful_error(self, tmp_path: Path) -> None:
        """Unresolvable @-mention must not crash; the surrounding content is still injected."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(
            modes_dir,
            "broken",
            body=(
                "# Broken Mode\n"
                "Some text before.\n"
                "@superpowers:context/nonexistent.md\n"
                "Some text after."
            ),
        )

        coordinator = _make_coordinator(active_mode="broken")
        resolver = MagicMock()
        # Resolver returns None for an unknown path
        resolver.resolve = MagicMock(return_value=None)
        coordinator.get_capability = MagicMock(
            side_effect=lambda key: resolver if key == "mention_resolver" else None
        )

        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "inject_context", (
            "Invalid @-mention must not prevent context injection; "
            f"got action={result.action!r}"
        )
        content = result.context_injection
        assert content is not None, (
            "context_injection should not be None when action is inject_context"
        )
        assert "Some text before." in content, (
            "Content before the invalid @-mention must still be injected"
        )
        assert "Some text after." in content, (
            "Content after the invalid @-mention must still be injected"
        )
        assert "@superpowers:context/nonexistent.md" not in content, (
            "The unresolvable @-mention line must be removed from the injected context"
        )
