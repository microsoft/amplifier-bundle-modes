"""Regression tests: documentation must describe shortcut semantics.

The original bug (papayne's systems-design bundle) was caused by
context/modes-instructions.md omitting `shortcut:` entirely. These tests
prevent silent doc drift. Strengthened per design §9.6 (M1): multi-term
presence check, not a single keyword grep — a deprecation comment cannot
satisfy the assertion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Locate bundle root — three parents up from this file's package dir.
# modules/hooks-mode/tests/test_docs_parity.py → bundle root is parents[3].
BUNDLE_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_TERMS = ["shortcut", "default", "name", "false"]


@pytest.mark.parametrize(
    "relpath",
    [
        "context/modes-instructions.md",
        "README.md",
    ],
)
def test_documentation_describes_shortcut_semantics(relpath: str) -> None:
    path = BUNDLE_ROOT / relpath
    assert path.is_file(), f"expected doc file missing: {path}"
    content = path.read_text(encoding="utf-8").lower()
    missing = [t for t in REQUIRED_TERMS if t not in content]
    assert not missing, (
        f"{relpath} is missing required documentation terms: {missing}. "
        f"The file must document: the shortcut field, that it defaults "
        f"to the mode's name, and that `shortcut: false` disables it. "
        f"See design doc §9.6 (docs/designs/default-shortcut-to-name.md)."
    )
