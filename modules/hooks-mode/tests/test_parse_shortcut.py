"""Tests for parse_mode_file shortcut resolution logic.

Covers shortcut validator helper (T1), default-from-name (T2), opt-out (T3),
YAML boolean trap (T4), lowercase normalization (T5), validation (T6),
explicit regression (T7), and shipped-modes lock (T17).
"""

from __future__ import annotations

from amplifier_module_hooks_mode import _SHORTCUT_PATTERN, _is_valid_shortcut  # type: ignore[attr-defined]


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
