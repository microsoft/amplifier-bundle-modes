"""Lean-head guardrail for amplifier-bundle-modes (model_performance-va53).

WHAT THIS PROTECTS
------------------
Two artifacts of this bundle render into the head of *every* request of *every*
session, whether or not a mode is ever activated:

  1. ``context/modes-instructions.md`` -- injected as a ``<context_file>`` span.
  2. the ``mode`` tool's ``description`` -- part of the tool-schema block.

``model_performance-g7h3`` bought 98 end-to-end runs ($428.10) measuring the
lean head:

    primary (VALID only, n 11/8)   -13.57%  $/task, 95% CI [-22.27%, -4.86%]

with all three pre-registered estimators excluding zero. Co-primary quality is
CITED from ``model_performance-5zp``: one-sided 95% lower bound -7.15 pp against
the frozen -10 pp non-inferiority margin -- CLEARS. Neither is re-bought here;
this file is a pure-Python, filesystem-only, no-network pin so the measured text
cannot silently regrow or drift.

WHAT EACH ASSERTION CAN AND CANNOT PROVE
----------------------------------------
* The BYTE PINS prove today's text is character-for-character the v1 text that
  was measured. That is fully proven here, offline.
* The CHAR BUDGETS prove the artifact has not regrown. Pinned PER ARTIFACT,
  never to a whole-head absolute -- zc6t measured a real head at 320,410 chars
  against the parent item's 48,249 figure, so any whole-head number in a
  per-repo test would be pinning a fiction.
* The FIDELITY assertions prove that every rule, command and pointer that was
  present in the stock text is still present in the lean text. They pass on BOTH
  arms by construction: that is the point -- a saving bought by deleting a real
  instruction is not a saving, it is an untraceable behaviour change.
* Nothing here proves the cache/cost behaviour on a live wire. That half is
  measured, not asserted (g7h3's 98 runs).

FAIL-BEFORE / PASS-AFTER
------------------------
Against the pre-change (stock, 4,870-char) ``context/modes-instructions.md``,
``test_modes_instructions_byte_pinned_to_v1`` and
``test_context_file_char_budget`` FAIL, and every ``mode``-description
assertion PASSES -- because the shipped ``mode`` description was already
byte-identical to v1 and is deliberately left untouched (zc6t finding F3).
See ``docs/lanes/3ahq-leanhead-modes/DONE-NOTE.md`` for the recorded transcripts.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

# modules/hooks-mode/tests/test_lean_head_guardrail.py -> bundle root is parents[3].
BUNDLE_ROOT = Path(__file__).resolve().parents[3]
PINS_FILE = Path(__file__).resolve().parent / "fixtures" / "lean-head-v1" / "v1_pins.json"

CONTEXT_FILE_REL = "context/modes-instructions.md"
CONTEXT_FILE = BUNDLE_ROOT / "context" / "modes-instructions.md"
TOOL_MODE_SOURCE = BUNDLE_ROOT / "modules" / "tool-mode" / "amplifier_module_tool_mode" / "__init__.py"

# --- per-artifact char budgets ----------------------------------------------
#
# Chars, not bytes and not tokens -- the published head census is in chars, so
# these can be added to it directly. Each budget is the MEASURED lean size,
# pinned exactly. A budget set above what shipped would let the head regrow up
# to it silently, which is the whole failure mode.
LEAN_CHARS = {CONTEXT_FILE_REL: 2403, "tool:mode": 198}

# What the same artifacts measured BEFORE this change, so the saving is a number
# in the repo rather than a claim in a commit message.
STOCK_CHARS = {CONTEXT_FILE_REL: 4870, "tool:mode": 198}

# --- fidelity: what must survive the rewrite --------------------------------
#
# "Fidelity beats compression at every point of conflict." Each entry was
# present in the stock text and must still be present in the lean text.

# Exact, case-sensitive: commands, config keys, pointers, literal syntax.
REQUIRED_CODE_LITERALS = [
    "`/mode <name>`",
    "`/modes`",
    "`/mode off`",
    '<system-reminder source="mode-<name>">',
    "`[mode]>`",
    "`safe`",
    "`warn`",
    "`confirm`",
    "`block`",
    "`default_action`",
    "`hooks-mode`",
    'infrastructure_tools: ["mode", "todo"]',
    "`tools.safe`",
    "mode-schema-reference.md",
    "§3.4",
    "`.amplifier/modes/`",
    "`~/.amplifier/modes/`",
    "@modes:context/mode-schema-reference.md",
    "mode-author",
    'mode(operation="set", name="plan")',
    'mode(operation="set"|"clear"|"list"|"current")',
    "`todo`",
    "`delegate`",
    "`mode`",
]

# Case-insensitive: prose that may legitimately be re-worded around the edges
# but whose substance must remain.
REQUIRED_PROSE = [
    "runtime behavior overlays",
    "yaml frontmatter",
    "skills-visibility list",
    "tools schema",
    "gate policy",
    "capabilities are ephemeral",
    "project",
    "user-global",
    "markdown",
]

# The four operations the `mode` tool accepts. All four must be reachable from
# the context file's own `mode(operation=...)` constructs -- the lean text
# collapses them into alternation forms rather than a four-row table, which is
# a presentation change, not a dropped rule.
REQUIRED_MODE_OPERATIONS = {"set", "clear", "list", "current"}

# The four tool policies, each with the behaviour word that makes it meaningful.
REQUIRED_POLICY_BEHAVIOURS = {
    "safe": "normal",
    "warn": "retry",
    "confirm": "approval",
    "block": "disabled",
}


def _pins() -> dict:
    return json.loads(PINS_FILE.read_text(encoding="utf-8"))


def _context_text() -> str:
    return CONTEXT_FILE.read_text(encoding="utf-8")


def _shipped_mode_description() -> str:
    """Extract ModeTool.description from source, without importing the module.

    Parsed rather than imported so the pin holds with no runtime dependencies
    and no import side effects.
    """
    tree = ast.parse(TOOL_MODE_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "description" for t in stmt.targets
            ):
                return ast.literal_eval(stmt.value)
    pytest.fail(f"no class-level `description` assignment found in {TOOL_MODE_SOURCE}")


# --- the vendored fixture itself --------------------------------------------


def test_vendored_v1_pins_are_self_consistent() -> None:
    """The fixture's own sha256/char records must match its own text.

    Guards against a hand-edit of the vendored copy, which would silently move
    the pin instead of failing it.
    """
    pins = _pins()
    ctx = pins["context_files"][CONTEXT_FILE_REL]
    mode = pins["tool_descriptions"]["mode"]
    assert hashlib.sha256(ctx.encode()).hexdigest() == pins["sha256"][CONTEXT_FILE_REL]
    assert hashlib.sha256(mode.encode()).hexdigest() == pins["sha256"]["mode"]
    assert len(ctx) == pins["chars"][CONTEXT_FILE_REL] == LEAN_CHARS[CONTEXT_FILE_REL]
    assert len(mode) == pins["chars"]["mode"] == LEAN_CHARS["tool:mode"]


# --- (1) byte pins ----------------------------------------------------------


def test_modes_instructions_byte_pinned_to_v1() -> None:
    """context/modes-instructions.md must be byte-identical to the v1 text.

    This is the assertion that goes RED against the pre-change stock text.
    """
    expected = _pins()["context_files"][CONTEXT_FILE_REL]
    actual = _context_text()
    assert actual == expected, (
        f"{CONTEXT_FILE_REL} has drifted from the measured v1 lean text.\n"
        f"  expected {len(expected)} chars, sha256 {hashlib.sha256(expected.encode()).hexdigest()}\n"
        f"  actual   {len(actual)} chars, sha256 {hashlib.sha256(actual.encode()).hexdigest()}\n"
        "If the change is intended, re-measure the head and update the vendored "
        "fixture in the same commit -- never edit one without the other."
    )


def test_mode_tool_description_byte_pinned_to_v1() -> None:
    """The `mode` tool description was ALREADY byte-identical to v1 (198 chars).

    zc6t finding F3: no change was warranted and none was made. Pinning it is
    what stops the already-correct text drifting away from v1 later. This
    assertion passes on BOTH arms -- before and after the context-file change.
    """
    expected = _pins()["tool_descriptions"]["mode"]
    actual = _shipped_mode_description()
    assert actual == expected, (
        "The `mode` tool description has drifted from the measured v1 text.\n"
        f"  expected: {expected!r}\n"
        f"  actual:   {actual!r}"
    )


# --- (2) per-artifact char budgets ------------------------------------------


def test_context_file_char_budget() -> None:
    """Pinned per artifact, never to a whole-head absolute."""
    actual = len(_context_text())
    budget = LEAN_CHARS[CONTEXT_FILE_REL]
    assert actual == budget, (
        f"{CONTEXT_FILE_REL} is {actual} chars, budget {budget} "
        f"(stock was {STOCK_CHARS[CONTEXT_FILE_REL]}). "
        "This file renders into the head of every request of every session."
    )


def test_mode_description_char_budget() -> None:
    actual = len(_shipped_mode_description())
    assert actual == LEAN_CHARS["tool:mode"], (
        f"`mode` description is {actual} chars, budget {LEAN_CHARS['tool:mode']}."
    )


def test_recorded_saving_is_arithmetically_consistent() -> None:
    """The saving is a number in the repo, not a claim in a commit message."""
    saving = STOCK_CHARS[CONTEXT_FILE_REL] - LEAN_CHARS[CONTEXT_FILE_REL]
    assert saving == 2467
    assert STOCK_CHARS["tool:mode"] - LEAN_CHARS["tool:mode"] == 0, (
        "`mode` was already at v1; a non-zero saving here means someone edited it."
    )


# --- (3) fidelity -----------------------------------------------------------


@pytest.mark.parametrize("literal", REQUIRED_CODE_LITERALS)
def test_required_code_literal_survives(literal: str) -> None:
    assert literal in _context_text(), (
        f"{literal!r} was present in the stock text and is missing from "
        f"{CONTEXT_FILE_REL}. Fidelity beats compression: restore it."
    )


@pytest.mark.parametrize("phrase", REQUIRED_PROSE)
def test_required_prose_survives(phrase: str) -> None:
    assert phrase.lower() in _context_text().lower(), (
        f"{phrase!r} was present in the stock text and is missing from {CONTEXT_FILE_REL}."
    )


def test_all_four_mode_operations_are_stated() -> None:
    """All four operation values must be reachable, in any presentation form."""
    found: set[str] = set()
    for match in re.finditer(r"mode\(operation=([^,)]*)", _context_text()):
        found |= set(re.findall(r'"([a-z]+)"', match.group(1)))
    missing = REQUIRED_MODE_OPERATIONS - found
    assert not missing, (
        f"mode operations {sorted(missing)} are not stated in {CONTEXT_FILE_REL}. "
        f"Found: {sorted(found)}."
    )


@pytest.mark.parametrize(("policy", "behaviour"), sorted(REQUIRED_POLICY_BEHAVIOURS.items()))
def test_tool_policy_and_its_behaviour_survive(policy: str, behaviour: str) -> None:
    text = _context_text().lower()
    assert f"`{policy}`" in text, f"tool policy `{policy}` is missing from {CONTEXT_FILE_REL}."
    assert behaviour in text, (
        f"tool policy `{policy}` is named but its behaviour ({behaviour!r}) is missing."
    )


def test_infrastructure_tools_bypass_survives() -> None:
    """The single most load-bearing rule in this file.

    Without it an agent in a `default_action: block` mode believes it cannot
    call `mode` or `todo` and is trapped.
    """
    text = _context_text()
    for fragment in (
        'infrastructure_tools: ["mode", "todo"]',
        "`hooks-mode`",
        "`default_action`",
        "`tools.safe`",
        "§3.4",
    ):
        assert fragment in text, f"infrastructure-tools bypass rule lost {fragment!r}."
    lowered = text.lower()
    assert "bypass" in lowered and "not a trap" in lowered, (
        "the bypass rule must still say that a `default_action: block` mode is NOT a trap."
    )
