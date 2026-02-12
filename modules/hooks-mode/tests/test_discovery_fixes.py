"""Tests for A1 discovery fixes."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from amplifier_module_hooks_mode import ModeDiscovery


def _create_mode_file(path: Path, name: str, description: str = "") -> Path:
    """Helper: create a minimal mode .md file with valid YAML frontmatter."""
    mode_file = path / f"{name}.md"
    mode_file.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{description or name + ' mode'}"
              tools:
                safe: [read_file]
              default_action: block
            ---
            # {name.title()} Mode
            You are in {name} mode.
        """),
        encoding="utf-8",
    )
    return mode_file


# ---------------------------------------------------------------------------
# Fix 1: source_base_paths support
# ---------------------------------------------------------------------------

class TestSourceBasePaths:
    """A1 fix: check source_base_paths on bundles."""

    def test_discovers_from_source_base_paths(self, tmp_path: Path) -> None:
        """Bundles with source_base_paths (no base_path) should be discovered."""
        bundle_dir = tmp_path / "multi-source-bundle"
        (bundle_dir / "modes").mkdir(parents=True)
        _create_mode_file(bundle_dir / "modes", "sourced", "From source_base_paths")

        bundle = MagicMock()
        bundle.base_path = None  # No direct base_path
        bundle.source_base_paths = [str(bundle_dir)]

        resolver = MagicMock()
        resolver.bundles = {"multi": bundle}

        coordinator = MagicMock()
        coordinator.get_capability = MagicMock(
            side_effect=lambda key: resolver if key == "mention_resolver" else None
        )

        discovery = ModeDiscovery(search_paths=[], coordinator=coordinator)
        result = discovery.find("sourced")
        assert result is not None
        assert result.name == "sourced"

    def test_discovers_from_multiple_source_base_paths(self, tmp_path: Path) -> None:
        """When source_base_paths has multiple entries, check all."""
        dir_a = tmp_path / "src-a"
        dir_b = tmp_path / "src-b"
        (dir_a / "modes").mkdir(parents=True)
        (dir_b / "modes").mkdir(parents=True)
        _create_mode_file(dir_a / "modes", "from-a", "From A")
        _create_mode_file(dir_b / "modes", "from-b", "From B")

        bundle = MagicMock()
        bundle.base_path = None
        bundle.source_base_paths = [str(dir_a), str(dir_b)]

        resolver = MagicMock()
        resolver.bundles = {"multi": bundle}

        coordinator = MagicMock()
        coordinator.get_capability = MagicMock(
            side_effect=lambda key: resolver if key == "mention_resolver" else None
        )

        discovery = ModeDiscovery(search_paths=[], coordinator=coordinator)
        modes = discovery.list_modes()
        names = [n for n, _ in modes]
        assert "from-a" in names
        assert "from-b" in names


# ---------------------------------------------------------------------------
# Fix 3: @mention path deferred resolution
# ---------------------------------------------------------------------------

class TestMentionPathResolution:
    """A1 fix: @mention paths in search_paths config."""

    def test_at_mention_path_resolved_lazily(self, tmp_path: Path) -> None:
        """search_paths with @namespace:path should resolve via mention_resolver."""
        bundle_dir = tmp_path / "superpowers"
        modes_dir = bundle_dir / "modes"
        modes_dir.mkdir(parents=True)
        _create_mode_file(modes_dir, "brainstorm", "Brainstorm mode")

        # Mock a bundle whose base_path resolves @superpowers -> bundle_dir
        bundle = MagicMock()
        bundle.base_path = str(bundle_dir)

        resolver = MagicMock()
        resolver.bundles = {"superpowers": bundle}

        coordinator = MagicMock()
        coordinator.get_capability = MagicMock(
            side_effect=lambda key: resolver if key == "mention_resolver" else None
        )

        # Pass @mention path as a deferred_path — NOT a filesystem path
        discovery = ModeDiscovery(
            search_paths=[],
            coordinator=coordinator,
            deferred_paths=["@superpowers:modes"],
        )

        result = discovery.find("brainstorm")
        assert result is not None
        assert result.name == "brainstorm"

    def test_at_mention_invalid_namespace_logged(self, tmp_path: Path) -> None:
        """Unknown @namespace should not crash, just skip."""
        resolver = MagicMock()
        resolver.bundles = {}  # No bundles

        coordinator = MagicMock()
        coordinator.get_capability = MagicMock(
            side_effect=lambda key: resolver if key == "mention_resolver" else None
        )

        discovery = ModeDiscovery(
            search_paths=[],
            coordinator=coordinator,
            deferred_paths=["@nonexistent:modes"],
        )

        # Should not crash
        assert discovery.list_modes() == []

    def test_regular_paths_still_work(self, tmp_path: Path) -> None:
        """Non-@ paths should still work as before."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        discovery = ModeDiscovery(search_paths=[modes_dir])
        result = discovery.find("plan")
        assert result is not None


# ---------------------------------------------------------------------------
# Fix 2: relative path resolution against working_dir
# ---------------------------------------------------------------------------

class TestRelativePathResolution:
    """A1 fix: relative paths in search_paths resolve against working_dir."""

    def test_relative_path_resolves_against_working_dir(self, tmp_path: Path) -> None:
        """'modes' in search_paths should resolve to working_dir/modes, not cwd/modes."""
        project_dir = tmp_path / "my-project"
        project_modes = project_dir / "custom-modes"
        project_modes.mkdir(parents=True)
        _create_mode_file(project_modes, "custom", "Custom mode")

        # Simulate mount() behavior: relative path with explicit working_dir
        working_dir = project_dir
        path_str = "custom-modes"
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = working_dir / p
        p = p.resolve()

        discovery = ModeDiscovery(search_paths=[p])
        result = discovery.find("custom")
        assert result is not None
        assert result.name == "custom"
