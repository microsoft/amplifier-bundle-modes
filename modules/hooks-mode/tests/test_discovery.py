"""Tests for ModeDiscovery class."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock


from amplifier_module_hooks_mode import ModeDiscovery, parse_mode_file


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


class TestParseMode:
    """Tests for parse_mode_file."""

    def test_valid_mode_file(self, tmp_path: Path) -> None:
        mode_file = _create_mode_file(tmp_path, "plan", "Think and discuss")
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.name == "plan"
        assert result.description == "Think and discuss"
        assert result.safe_tools == ["read_file", "grep"]
        assert result.default_action == "block"
        assert "You are in plan mode." in result.context

    def test_missing_frontmatter(self, tmp_path: Path) -> None:
        mode_file = tmp_path / "bad.md"
        mode_file.write_text("# No frontmatter\nJust content.")
        assert parse_mode_file(mode_file) is None

    def test_missing_mode_section(self, tmp_path: Path) -> None:
        mode_file = tmp_path / "bad.md"
        mode_file.write_text("---\nother: stuff\n---\nContent")
        assert parse_mode_file(mode_file) is None

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        assert parse_mode_file(tmp_path / "nonexistent.md") is None


class TestModeDiscovery:
    """Tests for ModeDiscovery search path behavior."""

    def test_find_from_explicit_search_path(self, tmp_path: Path) -> None:
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        discovery = ModeDiscovery(search_paths=[modes_dir])
        result = discovery.find("plan")
        assert result is not None
        assert result.name == "plan"

    def test_find_returns_none_for_unknown(self, tmp_path: Path) -> None:
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        assert discovery.find("nonexistent") is None

    def test_list_modes(self, tmp_path: Path) -> None:
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")
        _create_mode_file(modes_dir, "review", "Review mode")

        discovery = ModeDiscovery(search_paths=[modes_dir])
        modes = discovery.list_modes()
        names = [name for name, _desc, _source in modes]
        assert "plan" in names
        assert "review" in names

    def test_first_path_wins_precedence(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        _create_mode_file(dir_a, "plan", "From A")
        _create_mode_file(dir_b, "plan", "From B")

        discovery = ModeDiscovery(search_paths=[dir_a, dir_b])
        result = discovery.find("plan")
        assert result is not None
        assert result.description == "From A"

    def test_add_search_path(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        _create_mode_file(dir_b, "extra", "Extra mode")

        discovery = ModeDiscovery(search_paths=[dir_a])
        assert discovery.find("extra") is None

        discovery.add_search_path(dir_b)
        result = discovery.find("extra")
        assert result is not None
        assert result.name == "extra"

    def test_cache_behavior(self, tmp_path: Path) -> None:
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        discovery = ModeDiscovery(search_paths=[modes_dir])
        # First call parses file
        result1 = discovery.find("plan")
        # Second call should return cached
        result2 = discovery.find("plan")
        assert result1 is result2
        # After clear, re-parses
        discovery.clear_cache()
        result3 = discovery.find("plan")
        assert result3 is not result1
        assert result3 is not None
        assert result3.name == "plan"


class TestBundleDiscovery:
    """Tests for _ensure_bundle_discovery (lazy bundle scanning)."""

    def _make_coordinator_with_bundles(self, bundle_map: dict[str, Path]) -> MagicMock:
        """Create a mock coordinator with bundles on the resolver."""
        bundles = {}
        for namespace, base_path in bundle_map.items():
            bundle = MagicMock()
            bundle.base_path = str(base_path)
            bundles[namespace] = bundle

        resolver = MagicMock()
        resolver.bundles = bundles

        coordinator = MagicMock()
        coordinator.get_capability = MagicMock(
            side_effect=lambda key: resolver if key == "mention_resolver" else None
        )
        return coordinator

    def test_discovers_modes_from_composed_bundles(self, tmp_path: Path) -> None:
        bundle_a = tmp_path / "bundle-a"
        bundle_a_modes = bundle_a / "modes"
        bundle_a_modes.mkdir(parents=True)
        _create_mode_file(bundle_a_modes, "brainstorm", "Brainstorm mode")

        coordinator = self._make_coordinator_with_bundles({"bundle-a": bundle_a})
        discovery = ModeDiscovery(search_paths=[], coordinator=coordinator)

        result = discovery.find("brainstorm")
        assert result is not None
        assert result.name == "brainstorm"

    def test_discovers_from_multiple_bundles(self, tmp_path: Path) -> None:
        bundle_a = tmp_path / "bundle-a"
        bundle_b = tmp_path / "bundle-b"
        (bundle_a / "modes").mkdir(parents=True)
        (bundle_b / "modes").mkdir(parents=True)
        _create_mode_file(bundle_a / "modes", "alpha", "Alpha mode")
        _create_mode_file(bundle_b / "modes", "beta", "Beta mode")

        coordinator = self._make_coordinator_with_bundles(
            {
                "a": bundle_a,
                "b": bundle_b,
            }
        )
        discovery = ModeDiscovery(search_paths=[], coordinator=coordinator)

        modes = discovery.list_modes()
        names = [n for n, _desc, _source in modes]
        assert "alpha" in names
        assert "beta" in names

    def test_skips_bundles_without_modes_dir(self, tmp_path: Path) -> None:
        bundle_a = tmp_path / "bundle-a"
        bundle_a.mkdir()
        # No modes/ subdirectory

        coordinator = self._make_coordinator_with_bundles({"a": bundle_a})
        discovery = ModeDiscovery(search_paths=[], coordinator=coordinator)
        assert discovery.list_modes() == []

    def test_no_coordinator_skips_bundle_discovery(self, tmp_path: Path) -> None:
        discovery = ModeDiscovery(search_paths=[], coordinator=None)
        # Should not crash — just returns empty
        assert discovery.list_modes() == []

    def test_no_mention_resolver_logs_warning(self, tmp_path: Path) -> None:
        coordinator = MagicMock()
        coordinator.get_capability = MagicMock(return_value=None)

        discovery = ModeDiscovery(search_paths=[], coordinator=coordinator)
        # Should not crash
        assert discovery.list_modes() == []

    def test_app_mention_resolver_wrapper(self, tmp_path: Path) -> None:
        """When resolver is AppMentionResolver, reach through .foundation_resolver."""
        bundle_a = tmp_path / "bundle-a"
        (bundle_a / "modes").mkdir(parents=True)
        _create_mode_file(bundle_a / "modes", "deep", "Deep mode")

        inner_resolver = MagicMock()
        inner_resolver.bundles = {
            "a": MagicMock(base_path=str(bundle_a)),
        }

        # Outer resolver has no .bundles, but has .foundation_resolver
        outer_resolver = MagicMock(spec=[])
        outer_resolver.foundation_resolver = inner_resolver

        coordinator = MagicMock()
        coordinator.get_capability = MagicMock(
            side_effect=lambda key: (
                outer_resolver if key == "mention_resolver" else None
            )
        )

        discovery = ModeDiscovery(search_paths=[], coordinator=coordinator)
        result = discovery.find("deep")
        assert result is not None
        assert result.name == "deep"

    def test_discovery_runs_only_once(self, tmp_path: Path) -> None:
        bundle_a = tmp_path / "bundle-a"
        (bundle_a / "modes").mkdir(parents=True)
        _create_mode_file(bundle_a / "modes", "once", "Once mode")

        coordinator = self._make_coordinator_with_bundles({"a": bundle_a})
        discovery = ModeDiscovery(search_paths=[], coordinator=coordinator)

        # First call triggers discovery
        discovery.find("once")
        # Second call should NOT re-query coordinator
        coordinator.get_capability.reset_mock()
        discovery.find("once")
        coordinator.get_capability.assert_not_called()
