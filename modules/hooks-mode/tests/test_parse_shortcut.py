"""Tests for parse_mode_file shortcut resolution logic.

Covers shortcut validator helper (T1), default-from-name (T2), opt-out (T3),
YAML boolean trap (T4), lowercase normalization (T5), validation (T6),
explicit regression (T7), and shipped-modes lock (T17).
"""

from __future__ import annotations

import logging
import pathlib
import textwrap
from pathlib import Path

import pytest

from amplifier_module_hooks_mode import _SHORTCUT_PATTERN, _is_valid_shortcut  # type: ignore[attr-defined]
from amplifier_module_hooks_mode import parse_mode_file


def _write_mode(
    tmp_path: Path, filename: str, frontmatter_body: str, markdown: str = "body"
) -> Path:
    p = tmp_path / filename
    p.write_text(f"---\n{frontmatter_body}\n---\n{markdown}\n", encoding="utf-8")
    return p


class TestShortcutValidator:
    def test_regex_pattern_is_lowercase_only(self):
        assert _SHORTCUT_PATTERN == r"^[a-z][a-z0-9_-]*$"

    def test_valid_lowercase_identifier(self):
        assert _is_valid_shortcut("plan") is True
        assert _is_valid_shortcut("systems-design") is True
        assert _is_valid_shortcut("perf_audit") is True
        assert _is_valid_shortcut("x1") is True

    def test_rejects_leading_digit(self):
        assert _is_valid_shortcut("0mode") is False

    def test_rejects_leading_hyphen(self):
        assert _is_valid_shortcut("-mode") is False

    def test_rejects_uppercase(self):
        assert _is_valid_shortcut("MyMode") is False

    def test_rejects_spaces_and_slashes(self):
        assert _is_valid_shortcut("my mode") is False
        assert _is_valid_shortcut("my/mode") is False

    def test_rejects_empty(self):
        assert _is_valid_shortcut("") is False


class TestShortcutDefaultFromName:
    def test_key_omitted_defaults_to_name(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "explore.md",
            textwrap.dedent("""
            mode:
              name: explore
              description: d
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        mode_def = parse_mode_file(f)
        assert mode_def is not None
        assert mode_def.shortcut == "explore"  # §9.1 case 3

    def test_key_omitted_and_name_omitted_defaults_to_stem(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "foo.md",
            textwrap.dedent("""
            mode:
              description: d
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        mode_def = parse_mode_file(f)
        assert mode_def is not None
        assert mode_def.shortcut == "foo"  # §9.1 case 10


class TestShortcutOptOut:
    def test_false_opts_out(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "beta.md",
            textwrap.dedent("""
            mode:
              name: beta
              shortcut: false
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        assert parse_mode_file(f).shortcut is None  # type: ignore[union-attr]  # §9.1 case 4

    def test_null_tolerated_as_opt_out(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "beta.md",
            textwrap.dedent("""
            mode:
              name: beta
              shortcut: null
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        assert parse_mode_file(f).shortcut is None  # type: ignore[union-attr]  # §9.1 case 5

    def test_empty_string_tolerated_as_opt_out(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "beta.md",
            textwrap.dedent("""
            mode:
              name: beta
              shortcut: ""
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        assert parse_mode_file(f).shortcut is None  # type: ignore[union-attr]  # §9.1 case 6

    def test_whitespace_only_string_opts_out(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "beta.md",
            textwrap.dedent("""
            mode:
              name: beta
              shortcut: "   "
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        assert parse_mode_file(f).shortcut is None  # type: ignore[union-attr]  # §7.5


class TestShortcutYamlBooleanTrap:
    def test_yaml_yes_warns_and_defaults(self, tmp_path, caplog):
        f = _write_mode(
            tmp_path,
            "alpha.md",
            textwrap.dedent("""
            mode:
              name: alpha
              shortcut: yes
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            mode_def = parse_mode_file(f)
        assert mode_def.shortcut == "alpha"  # type: ignore[union-attr]  # §9.1 case 12a — defaults from name
        assert any("YAML boolean" in r.message for r in caplog.records)

    def test_yaml_true_warns_and_defaults(self, tmp_path, caplog):
        f = _write_mode(
            tmp_path,
            "alpha.md",
            textwrap.dedent("""
            mode:
              name: alpha
              shortcut: true
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            mode_def = parse_mode_file(f)
        assert mode_def.shortcut == "alpha"  # type: ignore[union-attr]  # §9.1 case 12b
        assert any("YAML boolean" in r.message for r in caplog.records)

    def test_yaml_on_warns_and_defaults(self, tmp_path, caplog):
        f = _write_mode(
            tmp_path,
            "alpha.md",
            textwrap.dedent("""
            mode:
              name: alpha
              shortcut: on
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            mode_def = parse_mode_file(f)
        assert mode_def.shortcut == "alpha"  # type: ignore[union-attr]  # §9.1 case 12c
        assert any("YAML boolean" in r.message for r in caplog.records)


class TestShortcutLowercase:
    def test_explicit_mixed_case_lowercased(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: m
              shortcut: MyMode
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        assert parse_mode_file(f).shortcut == "mymode"  # type: ignore[union-attr]  # §9.1 case 14

    def test_name_mixed_case_lowercased_in_default(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: MyMode
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        assert parse_mode_file(f).shortcut == "mymode"  # type: ignore[union-attr]  # §9.1 case 13


class TestShortcutValidation:
    def test_whitespace_interior_invalid(self, tmp_path, caplog):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: m
              shortcut: "  my mode  "
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            mode_def = parse_mode_file(f)
        assert mode_def.shortcut is None  # type: ignore[union-attr]  # §9.1 case 7
        assert any(
            "not a valid slash-command identifier" in r.message for r in caplog.records
        )

    def test_slash_invalid(self, tmp_path, caplog):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: m
              shortcut: "my/mode"
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            mode_def = parse_mode_file(f)
        assert mode_def.shortcut is None  # type: ignore[union-attr]  # §9.1 case 8
        assert any(
            "not a valid slash-command identifier" in r.message for r in caplog.records
        )

    def test_invalid_name_propagates_to_default_shortcut(self, tmp_path, caplog):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: "my mode"
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            mode_def = parse_mode_file(f)
        assert mode_def is not None
        assert mode_def.name == "my mode"  # mode still loads
        assert mode_def.shortcut is None  # §9.1 case 9 — invalid

    def test_leading_digit_invalid(self, tmp_path, caplog):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: m
              shortcut: "0mode"
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            mode_def = parse_mode_file(f)
        assert mode_def.shortcut is None  # type: ignore[union-attr]  # §9.1 case 15
        assert any(
            "not a valid slash-command identifier" in r.message for r in caplog.records
        )


class TestShortcutExplicitRegressions:
    def test_explicit_matches_name(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: plan
              shortcut: plan
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        assert parse_mode_file(f).shortcut == "plan"  # type: ignore[union-attr]  # §9.1 case 1

    def test_explicit_differs_from_name(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: plan
              shortcut: p
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        assert parse_mode_file(f).shortcut == "p"  # type: ignore[union-attr]  # §9.1 case 2

    def test_quoted_false_is_literal_shortcut_named_false(self, tmp_path):
        f = _write_mode(
            tmp_path,
            "m.md",
            textwrap.dedent("""
            mode:
              name: m
              shortcut: "false"
              tools: {safe: []}
              default_action: block
        """).strip(),
        )
        # YAML string "false" (quoted) is a real string, not a boolean → registers /false.
        # Distinguished from `shortcut: false` (unquoted) which is the opt-out.
        # Design §5.2 Note; §9.1 case 11.
        assert parse_mode_file(f).shortcut == "false"  # type: ignore[union-attr]


class TestIntegrationFakeBundle:
    def test_fake_bundle_layout(self, tmp_path):
        """§9.3 integration: three modes — omitted / opt-out / explicit."""
        from unittest.mock import MagicMock

        from amplifier_module_hooks_mode import ModeDiscovery

        modes = tmp_path / "fake-bundle" / "modes"
        modes.mkdir(parents=True)
        (modes / "alpha.md").write_text(
            textwrap.dedent("""
                ---
                mode: {name: alpha, tools: {safe: []}, default_action: block}
                ---
                body
            """).strip()
            + "\n"
        )
        (modes / "beta.md").write_text(
            textwrap.dedent("""
                ---
                mode: {name: beta, shortcut: false, tools: {safe: []}, default_action: block}
                ---
                body
            """).strip()
            + "\n"
        )
        (modes / "gamma.md").write_text(
            textwrap.dedent("""
                ---
                mode: {name: gamma, shortcut: g, tools: {safe: []}, default_action: block}
                ---
                body
            """).strip()
            + "\n"
        )
        disc = ModeDiscovery(search_paths=[(modes, "test")])
        disc._coordinator = MagicMock()
        disc._coordinator.get_capability.return_value = None
        result = disc.get_shortcuts()
        assert result == {"alpha": "alpha", "g": "gamma"}  # no `beta` key


BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestShippedModesUnchanged:
    """§8: the three shipped modes (careful, plan, explore) keep explicit shortcuts
    as in-repo reference. This test prevents an accidental removal."""

    @pytest.mark.parametrize(
        "mode_name,expected_shortcut",
        [
            ("careful", "careful"),
            ("plan", "plan"),
            ("explore", "explore"),
        ],
    )
    def test_shipped_mode_shortcut(
        self, mode_name: str, expected_shortcut: str
    ) -> None:
        path = BUNDLE_ROOT / "modes" / f"{mode_name}.md"
        assert path.is_file(), f"shipped mode file missing: {path}"
        mode_def = parse_mode_file(path)
        assert mode_def is not None
        assert mode_def.shortcut == expected_shortcut, (
            f"Shipped mode {mode_name} lost its explicit shortcut. "
            f"Per design §8, shipped modes keep explicit shortcut: as reference."
        )

    def test_shipped_mode_files_retain_explicit_shortcut_line(self) -> None:
        """Defense in depth — read the raw file and check the literal `shortcut:` token
        appears, so a refactor that removes the field (relying on the new default) would
        also fail this test. Prevents silent drift of the reference examples."""
        for name in ("careful", "plan", "explore"):
            text = (BUNDLE_ROOT / "modes" / f"{name}.md").read_text()
            assert "shortcut:" in text, (
                f"modes/{name}.md lost its explicit `shortcut:` line. Per design §8, "
                f"shipped modes are canonical reference examples and must keep the field."
            )
