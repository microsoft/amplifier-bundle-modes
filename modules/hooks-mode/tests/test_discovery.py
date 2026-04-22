"""Tests for ModeDiscovery class."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock


from amplifier_module_hooks_mode import ModeDefinition, ModeDiscovery, parse_mode_file


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

    def test_parse_allowed_transitions(self, tmp_path: Path) -> None:
        """parse_mode_file must extract allowed_transitions from mode: section."""
        mode_file = tmp_path / "strict.md"
        mode_file.write_text(
            textwrap.dedent("""\
                ---
                mode:
                  name: strict
                  description: Strict mode
                  allowed_transitions:
                    - plan
                    - review
                  default_action: block
                ---
                # Strict Mode
                You are in strict mode.
            """),
            encoding="utf-8",
        )
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.allowed_transitions == ["plan", "review"]

    def test_parse_allowed_transitions_absent_defaults_to_none(
        self, tmp_path: Path
    ) -> None:
        """When allowed_transitions is absent, parse_mode_file must return None (not [])."""
        mode_file = _create_mode_file(tmp_path, "basic", "Basic mode")
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.allowed_transitions is None

    def test_parse_allow_clear_false(self, tmp_path: Path) -> None:
        """parse_mode_file must extract allow_clear=False from mode: section."""
        mode_file = tmp_path / "locked.md"
        mode_file.write_text(
            textwrap.dedent("""\
                ---
                mode:
                  name: locked
                  description: Locked mode
                  allow_clear: false
                  default_action: block
                ---
                # Locked Mode
                You are in locked mode.
            """),
            encoding="utf-8",
        )
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.allow_clear is False

    def test_parse_allow_clear_absent_defaults_to_true(self, tmp_path: Path) -> None:
        """When allow_clear is absent, parse_mode_file must default to True."""
        mode_file = _create_mode_file(tmp_path, "basic2", "Basic mode")
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.allow_clear is True

    def test_allowed_transitions_inline_list_parsed(self, tmp_path: Path) -> None:
        mode_file = tmp_path / "guarded.md"
        mode_file.write_text(
            textwrap.dedent("""\
                ---
                mode:
                  name: guarded
                  description: "Guarded mode"
                  allowed_transitions: [next, other]
                  tools:
                    safe: [read_file]
                  default_action: block
                ---
                # Guarded Mode
                Content here.
            """),
            encoding="utf-8",
        )
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.allowed_transitions == ["next", "other"]

    def test_allow_clear_true_explicit_parsed(self, tmp_path: Path) -> None:
        mode_file = tmp_path / "open.md"
        mode_file.write_text(
            textwrap.dedent("""\
                ---
                mode:
                  name: open
                  description: "Open mode"
                  allow_clear: true
                  tools:
                    safe: [read_file]
                  default_action: block
                ---
                # Open Mode
                Content here.
            """),
            encoding="utf-8",
        )
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.allow_clear is True

    def test_missing_new_fields_uses_defaults(self, tmp_path: Path) -> None:
        """Backward compat: absent fields = permissive defaults."""
        mode_file = _create_mode_file(tmp_path, "legacy", "Legacy mode")
        result = parse_mode_file(mode_file)
        assert result is not None
        assert result.allowed_transitions is None  # None = any transition OK
        assert result.allow_clear is True  # True = clear is allowed


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


class TestModeDefinitionNewFields:
    """Task 1: ModeDefinition must have allowed_transitions and allow_clear fields."""

    def test_allowed_transitions_defaults_to_none(self) -> None:
        """allowed_transitions must default to None (unrestricted), not empty list."""
        mode = ModeDefinition(name="test")
        assert mode.allowed_transitions is None

    def test_allow_clear_defaults_to_true(self) -> None:
        """allow_clear must default to True (backward compatible)."""
        mode = ModeDefinition(name="test")
        assert mode.allow_clear is True

    def test_allowed_transitions_can_be_set_to_list(self) -> None:
        """allowed_transitions can be set to a list of mode names."""
        mode = ModeDefinition(name="test", allowed_transitions=["plan", "review"])
        assert mode.allowed_transitions == ["plan", "review"]

    def test_allow_clear_can_be_set_to_false(self) -> None:
        """allow_clear can be explicitly set to False."""
        mode = ModeDefinition(name="test", allow_clear=False)
        assert mode.allow_clear is False

    def test_existing_fields_unaffected(self) -> None:
        """Adding new fields must not change existing field behavior."""
        mode = ModeDefinition(
            name="plan",
            description="Think",
            default_action="block",
        )
        assert mode.name == "plan"
        assert mode.description == "Think"
        assert mode.default_action == "block"
        assert mode.safe_tools == []
        assert mode.warn_tools == []
        assert mode.confirm_tools == []
        assert mode.block_tools == []


class TestGetShortcutsNameAsValue:
    def test_default_shortcut_value_is_name(self, tmp_path):
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "alpha.md").write_text(
            textwrap.dedent("""
                ---
                mode:
                  name: alpha
                  tools: {safe: []}
                  default_action: block
                ---
                body
            """).strip()
            + "\n"
        )
        disc = ModeDiscovery(search_paths=[(modes_dir, "test")])
        disc._coordinator = MagicMock()
        disc._coordinator.capabilities = MagicMock()
        disc._coordinator.capabilities.get.return_value = None
        result = disc.get_shortcuts()
        assert result == {"alpha": "alpha"}  # §9.2 case 1

    def test_stem_differs_from_name(self, tmp_path):
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "my_mode.md").write_text(
            textwrap.dedent("""
                ---
                mode:
                  name: my-mode
                  tools: {safe: []}
                  default_action: block
                ---
                body
            """).strip()
            + "\n"
        )
        disc = ModeDiscovery(search_paths=[(modes_dir, "test")])
        disc._coordinator = MagicMock()
        disc._coordinator.get_capability.return_value = None
        result = disc.get_shortcuts()
        # Key = shortcut (defaults to name, lowercased) = "my-mode"
        # Value = mode_def.name = "my-mode" (NOT "my_mode" stem)
        assert result == {"my-mode": "my-mode"}  # §9.2 case 7 — MINOR-1


class TestGetShortcutsCollision:
    def test_collision_across_search_paths_logs_info(self, tmp_path, caplog):
        import logging

        path_a = tmp_path / "a" / "modes"
        path_a.mkdir(parents=True)
        path_b = tmp_path / "b" / "modes"
        path_b.mkdir(parents=True)
        for p, n in [(path_a, "review"), (path_b, "review")]:
            (p / "review.md").write_text(
                textwrap.dedent(f"""
                    ---
                    mode:
                      name: {n}
                      tools: {{safe: []}}
                      default_action: block
                    ---
                    body
                """).strip()
                + "\n"
            )
        disc = ModeDiscovery(search_paths=[(path_a, "a"), (path_b, "b")])
        disc._coordinator = MagicMock()
        disc._coordinator.get_capability.return_value = None
        with caplog.at_level(logging.INFO, logger="amplifier_module_hooks_mode"):
            result = disc.get_shortcuts()
        assert result == {"review": "review"}  # first-wins
        # Names equal -> `existing_name != mode_def.name` is False -> no log emitted.
        # Following §4.2 code (authoritative). §9.2 case 8 variant-1 prose corrected in Rev 2.
        # This test asserts the code behavior: same-name collisions are silent.
        assert not any("collision" in r.message.lower() for r in caplog.records)

    def test_collision_with_different_names_logs_info(self, tmp_path, caplog):
        """Two files claiming the same shortcut key but with different resolved names —
        the genuine collision case. §9.2 case 8 variant 2; MINOR-1 guard."""
        import logging

        path_a = tmp_path / "a" / "modes"
        path_a.mkdir(parents=True)
        path_b = tmp_path / "b" / "modes"
        path_b.mkdir(parents=True)
        (path_a / "review.md").write_text(
            textwrap.dedent("""
                ---
                mode: {name: review, tools: {safe: []}, default_action: block}
                ---
                body
            """).strip()
            + "\n"
        )
        (path_b / "review.md").write_text(
            textwrap.dedent("""
                ---
                mode: {name: review-other, shortcut: review, tools: {safe: []}, default_action: block}
                ---
                body
            """).strip()
            + "\n"
        )
        disc = ModeDiscovery(search_paths=[(path_a, "a"), (path_b, "b")])
        disc._coordinator = MagicMock()
        disc._coordinator.get_capability.return_value = None
        with caplog.at_level(logging.INFO, logger="amplifier_module_hooks_mode"):
            result = disc.get_shortcuts()
        assert result == {"review": "review"}  # first-wins by precedence
        assert any(
            "collision" in r.message.lower() and "review-other" in r.message
            for r in caplog.records
        )

    def test_explicit_shortcut_collision(self, tmp_path, caplog):
        """Two modes with explicit but conflicting shortcuts. §9.2 case 5."""
        import logging

        modes = tmp_path / "modes"
        modes.mkdir()
        (modes / "a.md").write_text(
            textwrap.dedent("""
                ---
                mode: {name: alpha, shortcut: x, tools: {safe: []}, default_action: block}
                ---
                body
            """).strip()
            + "\n"
        )
        (modes / "b.md").write_text(
            textwrap.dedent("""
                ---
                mode: {name: beta, shortcut: x, tools: {safe: []}, default_action: block}
                ---
                body
            """).strip()
            + "\n"
        )
        disc = ModeDiscovery(search_paths=[(modes, "test")])
        disc._coordinator = MagicMock()
        disc._coordinator.get_capability.return_value = None
        with caplog.at_level(logging.INFO, logger="amplifier_module_hooks_mode"):
            disc.get_shortcuts()
        assert any("collision" in r.message.lower() for r in caplog.records)

    def test_get_shortcuts_preserves_cache_precedence(self, tmp_path):
        """After get_shortcuts(), find() must return the highest-precedence mode_def.

        Regression test for the cache last-wins bug introduced in commit 94b3c20:
        get_shortcuts() was unconditionally writing self._cache[name] = mode_def for
        every file it parsed, so the last bundle wins in the cache even though the
        shortcuts dict itself correctly applied first-wins.  After the one-line fix
        (``if name not in self._cache``), find("review") must return bundle-A's mode_def.
        """
        from textwrap import dedent

        path_a = tmp_path / "a" / "modes"
        path_a.mkdir(parents=True)
        path_b = tmp_path / "b" / "modes"
        path_b.mkdir(parents=True)
        # Same stem + same YAML name, different descriptions so we can tell them apart.
        (path_a / "review.md").write_text(
            dedent("""\
                ---
                mode:
                  name: review
                  description: from bundle A
                ---
                """)
        )
        (path_b / "review.md").write_text(
            dedent("""\
                ---
                mode:
                  name: review
                  description: from bundle B
                ---
                """)
        )
        disc = ModeDiscovery(search_paths=[(path_a, "a"), (path_b, "b")])
        disc._coordinator = MagicMock()
        disc._coordinator.get_capability.return_value = None
        disc.get_shortcuts()  # triggers the cache writes
        result = disc.find("review")
        assert result is not None
        assert result.description == "from bundle A", (
            f"Expected bundle-A mode_def but got description={result.description!r}. "
            "Cache precedence not preserved — last-wins bug still present."
        )

    def test_invalid_shortcut_excluded_from_get_shortcuts(self, tmp_path):
        """§9.2 case 6 direct: a mode with an invalid shortcut is absent from get_shortcuts output."""
        from textwrap import dedent

        mode_dir = tmp_path / "modes"
        mode_dir.mkdir()
        (mode_dir / "bad.md").write_text(
            dedent(
                """\
            ---
            mode:
              name: bad
              shortcut: "bad name"
            ---
            """
            )
        )
        disc = ModeDiscovery(search_paths=[(mode_dir, "test")])
        disc._coordinator = MagicMock()
        disc._coordinator.get_capability.return_value = None
        shortcuts = disc.get_shortcuts()
        assert "bad name" not in shortcuts
        assert "bad" not in shortcuts  # the name itself shouldn't sneak in either
        assert shortcuts == {}  # nothing else is around in this tmp dir
