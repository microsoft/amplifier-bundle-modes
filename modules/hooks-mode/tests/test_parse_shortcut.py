"""Tests for parse_mode_file shortcut resolution logic.

Covers shortcut validator helper (T1), default-from-name (T2), opt-out (T3),
YAML boolean trap (T4), lowercase normalization (T5), validation (T6),
explicit regression (T7), and shipped-modes lock (T17).
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

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
