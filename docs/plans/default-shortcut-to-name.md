# Plan: Default `shortcut` to the mode's `name` when unset

**Status:** Gate 2 draft — awaiting CoE plan review (zen-architect REVIEW mode)
**Design doc:** [`docs/designs/default-shortcut-to-name.md`](../designs/default-shortcut-to-name.md) Rev 1 (Gate 1 APPROVED)
**Feature branch:** `feat/default-shortcut-to-name`
**Scope of change:** `amplifier-bundle-modes` bundle only. No kernel or CLI changes.
**Python / deps:** Python 3.10+ (existing requirement). No new dependencies. PyYAML, `pytest`, `pytest` `caplog` fixture already present.
**Estimated total effort:** 3–4 hours for a focused implementer (~18 tasks, S/M sized).
**Executor:** `superpowers:implementer` agent, executing tasks strictly in the listed order.

---

## 1. Scope summary

**In scope.** Implement the policy and mechanism approved in design §4–§8: default `shortcut` to the resolved `name` when the field is absent; treat `shortcut: false` as canonical opt-out; guard against YAML-boolean-truthy traps; lowercase-normalize shortcuts; validate against `^[a-z][a-z0-9_-]*$`; emit INFO collision logs in `get_shortcuts()`; update all author-facing documentation (`context/modes-instructions.md`, `README.md`, `bundle.md`, the `parse_mode_file` docstring, changelog) so the agent-facing and human-facing docs agree; and add a regression test that prevents the documentation from silently drifting out of parity again.

**Out of scope.** `ModeDefinition` dataclass shape changes; `list_modes()` behavior changes; CLI `CommandProcessor` changes; `mode` tool changes; existing shipped mode files (`modes/careful.md`, `modes/plan.md`, `modes/explore.md`) — these keep their explicit `shortcut:` fields as in-repo reference documentation. No PR, no merge, no commit to upstream. The plan produces a working-tree state and a local feature branch; shipping is a separate pipeline stage (DTU → git-ops → PR).

---

## 2. Pre-flight

### P0 — Create feature branch and establish green baseline

**Files touched:** (none)
**Design ref:** n/a (process)
**Sub-steps:**

1. `cd amplifier-bundle-modes`
2. Verify clean working tree except submodule additions from the parent session:
   `git status` — expect no staged changes.
3. Create the feature branch from `main`:
   `git checkout -b feat/default-shortcut-to-name`
4. Run the **baseline** test suite and capture exit code:
   `cd modules/hooks-mode && uv run pytest -q`
5. Confirm: exit code 0, all existing tests pass. This is the "green start" — any subsequent failure is attributable to this feature work, not inherited breakage.
6. Record baseline test count for later comparison (e.g. `34 passed in 0.42s` → expect `34 + N` after feature lands).

**Acceptance:** on `feat/default-shortcut-to-name`, `pytest` is green, and the baseline count is recorded.
**Size:** S

---

## 3. Task list (RED → GREEN → REFACTOR)

> **TDD protocol (non-negotiable).** For every code task: (a) write the failing test; (b) run and **observe** it fail with the documented failure mode — do not proceed otherwise; (c) make the smallest code change that passes; (d) run the single test and observe pass; (e) run the full module suite and observe no regressions; (f) commit with a conventional-commit message.
>
> **Incremental-state caveat.** Tasks T2–T7 each add one branch to the new `parse_mode_file` shortcut-resolution block. Until T6 (validation) lands, some edge-case inputs may produce an intermediate behavior that is neither "current" nor "final." Each task's **expected failure mode** field documents precisely what the test should observe at the moment the test is written. This is intentional: TDD requires each red phase to assert a specific, predicted failure so the test is known to be real.

### T1 — Extract shortcut validator helper and regex constant

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (top-of-module additions, near L26 after `logger = ...`)
- `modules/hooks-mode/tests/test_parse_shortcut.py` (NEW file)

**Design ref:** §4.1 step 5, §7.3

**Sub-steps:**

1. **RED** — Create `modules/hooks-mode/tests/test_parse_shortcut.py`. Add:
   ```python
   from amplifier_module_hooks_mode import _SHORTCUT_PATTERN, _is_valid_shortcut

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
   ```
2. Run `pytest modules/hooks-mode/tests/test_parse_shortcut.py -q`.
   **Expected failure mode:** `ImportError: cannot import name '_SHORTCUT_PATTERN' from 'amplifier_module_hooks_mode'`.
3. **GREEN** — In `__init__.py`, immediately after the `logger = logging.getLogger(__name__)` line (~L26), add:
   ```python
   _SHORTCUT_PATTERN = r"^[a-z][a-z0-9_-]*$"
   _SHORTCUT_RE = re.compile(_SHORTCUT_PATTERN)


   def _is_valid_shortcut(value: str) -> bool:
       """True iff `value` matches the shortcut identifier grammar (see design §7.3)."""
       return bool(_SHORTCUT_RE.match(value))
   ```
4. Re-run the new test file — expect all 7 tests green.
5. Run the full module suite — expect baseline + 7 passing.
6. **Commit:** `feat(hooks-mode): add _SHORTCUT_PATTERN and _is_valid_shortcut helper`

**Acceptance:** helper function and constant are importable from the module; all 7 new tests pass; no regressions.
**Size:** S

---

### T2 — `parse_mode_file`: default-from-name when `shortcut:` key is absent

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (L94–L106 — the `return ModeDefinition(...)` block)
- `modules/hooks-mode/tests/test_parse_shortcut.py`

**Design ref:** §4.1 step 1, §9.1 cases 3 and 10

**Sub-steps:**

1. **RED** — Append to `test_parse_shortcut.py`:
   ```python
   import textwrap
   from pathlib import Path
   from amplifier_module_hooks_mode import parse_mode_file

   def _write_mode(tmp_path: Path, filename: str, frontmatter_body: str, markdown: str = "body") -> Path:
       p = tmp_path / filename
       p.write_text(f"---\n{frontmatter_body}\n---\n{markdown}\n", encoding="utf-8")
       return p

   class TestShortcutDefaultFromName:
       def test_key_omitted_defaults_to_name(self, tmp_path):
           f = _write_mode(tmp_path, "explore.md", textwrap.dedent("""
               mode:
                 name: explore
                 description: d
                 tools: {safe: []}
                 default_action: block
           """).strip())
           mode_def = parse_mode_file(f)
           assert mode_def is not None
           assert mode_def.shortcut == "explore"  # §9.1 case 3

       def test_key_omitted_and_name_omitted_defaults_to_stem(self, tmp_path):
           f = _write_mode(tmp_path, "foo.md", textwrap.dedent("""
               mode:
                 description: d
                 tools: {safe: []}
                 default_action: block
           """).strip())
           mode_def = parse_mode_file(f)
           assert mode_def is not None
           assert mode_def.shortcut == "foo"  # §9.1 case 10
   ```
2. Run those two tests.
   **Expected failure mode:** `AssertionError: assert None == 'explore'` (and `None == 'foo'`). Current code returns `mode_config.get("shortcut")` which is `None` when absent.
3. **GREEN** — Replace the current `ModeDefinition` construction block (L94–L106) with a pre-resolved-shortcut form. Specifically, insert between L92 and L94:
   ```python
   resolved_name = mode_config.get("name", file_path.stem)

   if "shortcut" in mode_config:
       # (opt-out, bool-guard, string paths — added incrementally in T3/T4)
       shortcut = mode_config["shortcut"]
   else:
       shortcut = resolved_name
   ```
   Update the `return ModeDefinition(...)` call to use `name=resolved_name` and `shortcut=shortcut` instead of the inline `.get()` calls on those two fields.
4. Run the two new tests — expect green. Run the helper tests from T1 — expect green. Run the full suite — expect no regressions.
5. **Commit:** `feat(hooks-mode): default mode shortcut to name when field absent`

**Acceptance:** a mode file with no `shortcut:` key and an explicit `name:` produces `mode_def.shortcut == name`; with neither, falls back to filename stem. All prior tests still pass.
**Size:** M

---

### T3 — `parse_mode_file`: explicit opt-out via `shortcut: false` (and tolerated falsy variants)

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (the shortcut-resolution block added in T2)
- `modules/hooks-mode/tests/test_parse_shortcut.py`

**Design ref:** §4.1 step 4, §5, §9.1 cases 4, 5, 6

**Sub-steps:**

1. **RED** — Append:
   ```python
   class TestShortcutOptOut:
       def test_false_opts_out(self, tmp_path):
           f = _write_mode(tmp_path, "beta.md", textwrap.dedent("""
               mode:
                 name: beta
                 shortcut: false
                 tools: {safe: []}
                 default_action: block
           """).strip())
           assert parse_mode_file(f).shortcut is None  # §9.1 case 4

       def test_null_tolerated_as_opt_out(self, tmp_path):
           f = _write_mode(tmp_path, "beta.md", textwrap.dedent("""
               mode:
                 name: beta
                 shortcut: null
                 tools: {safe: []}
                 default_action: block
           """).strip())
           assert parse_mode_file(f).shortcut is None  # §9.1 case 5

       def test_empty_string_tolerated_as_opt_out(self, tmp_path):
           f = _write_mode(tmp_path, "beta.md", textwrap.dedent("""
               mode:
                 name: beta
                 shortcut: ""
                 tools: {safe: []}
                 default_action: block
           """).strip())
           assert parse_mode_file(f).shortcut is None  # §9.1 case 6

       def test_whitespace_only_string_opts_out(self, tmp_path):
           f = _write_mode(tmp_path, "beta.md", textwrap.dedent("""
               mode:
                 name: beta
                 shortcut: "   "
                 tools: {safe: []}
                 default_action: block
           """).strip())
           assert parse_mode_file(f).shortcut is None  # §7.5
   ```
2. Run.
   **Expected failure mode:** after T2, the stub in the `if "shortcut" in mode_config` branch just assigns `raw` directly — so `shortcut` is `False` / `None` / `""` / `"   "`. The `None` assertion passes incidentally for case 5; cases 4, 6, whitespace fail with `AssertionError: assert False is None` (etc.).
3. **GREEN** — Expand the branch:
   ```python
   if "shortcut" in mode_config:
       raw = mode_config["shortcut"]
       if raw is False or raw is None or raw == "" or raw == 0:
           shortcut = None
       else:
           shortcut = str(raw).strip() or None
   else:
       shortcut = resolved_name
   ```
4. Rerun new tests — green. Full suite — green.
5. **Commit:** `feat(hooks-mode): honor shortcut: false and tolerate falsy variants as opt-out`

**Acceptance:** `shortcut: false`, `null`, `""`, whitespace-only string all resolve to `mode_def.shortcut is None`. Default-from-name (T2) still works.
**Size:** M

---

### T4 — `parse_mode_file`: YAML boolean-truthy trap guard (`yes` / `true` / `on`)

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (the shortcut-resolution block)
- `modules/hooks-mode/tests/test_parse_shortcut.py`

**Design ref:** §4.1 step 2 (M2, Gate 1), §9.1 cases 12a, 12b, 12c

**Sub-steps:**

1. **RED** — Append:
   ```python
   import logging

   class TestShortcutYamlBooleanTrap:
       def test_yaml_yes_warns_and_defaults(self, tmp_path, caplog):
           f = _write_mode(tmp_path, "alpha.md", textwrap.dedent("""
               mode:
                 name: alpha
                 shortcut: yes
                 tools: {safe: []}
                 default_action: block
           """).strip())
           with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
               mode_def = parse_mode_file(f)
           assert mode_def.shortcut == "alpha"  # §9.1 case 12a — defaults from name
           assert any("YAML boolean" in r.message for r in caplog.records)

       def test_yaml_true_warns_and_defaults(self, tmp_path, caplog):
           # Same shape, `shortcut: true` — §9.1 case 12b
           ...

       def test_yaml_on_warns_and_defaults(self, tmp_path, caplog):
           # Same shape, `shortcut: on` — §9.1 case 12c
           ...
   ```
   (Implementer: write all three by parameterization or by inlined copies; the test body is identical except the YAML token.)
2. Run.
   **Expected failure mode:** PyYAML parses `yes`/`true`/`on` as Python `True`; current T3 code hits the `else: str(raw).strip()` branch → `shortcut = "True"`. Assertion `"True" == "alpha"` fails; no warning logged.
3. **GREEN** — Insert the `elif isinstance(raw, bool)` branch **between** the opt-out branch and the `else: str(raw).strip()` branch (ordering matters — the opt-out branch already matched `False` by identity, so only `True` reaches the `isinstance(raw, bool)` guard):
   ```python
   if "shortcut" in mode_config:
       raw = mode_config["shortcut"]
       if raw is False or raw is None or raw == "" or raw == 0:
           shortcut = None
       elif isinstance(raw, bool):  # True — YAML truthy trap (yes/true/on)
           logger.warning(
               "Mode file %s: shortcut value %r is a YAML boolean, not a string. "
               "To disable the shortcut, use `shortcut: false`. "
               "To use the default (the mode's name), omit the field. "
               "Treating as absent for this load.",
               file_path, raw,
           )
           shortcut = resolved_name
       else:
           shortcut = str(raw).strip() or None
   else:
       shortcut = resolved_name
   ```
4. Rerun — green. Full suite — green.
5. **Commit:** `feat(hooks-mode): guard against YAML-truthy shortcut values`

**Acceptance:** `shortcut: yes`/`true`/`on` all emit a WARNING and default to the mode's name. `shortcut: false` still opts out (not swallowed by the new guard — verified by re-running T3's tests).
**Size:** M

---

### T5 — `parse_mode_file`: lowercase normalization

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (the shortcut-resolution block)
- `modules/hooks-mode/tests/test_parse_shortcut.py`

**Design ref:** §4.1 step 5 (`.lower()`), §7.3 (MINOR-2, Gate 1), §9.1 cases 13, 14

**Sub-steps:**

1. **RED** — Append:
   ```python
   class TestShortcutLowercase:
       def test_explicit_mixed_case_lowercased(self, tmp_path):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: m
                 shortcut: MyMode
                 tools: {safe: []}
                 default_action: block
           """).strip())
           assert parse_mode_file(f).shortcut == "mymode"  # §9.1 case 14

       def test_name_mixed_case_lowercased_in_default(self, tmp_path):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: MyMode
                 tools: {safe: []}
                 default_action: block
           """).strip())
           assert parse_mode_file(f).shortcut == "mymode"  # §9.1 case 13
   ```
2. Run.
   **Expected failure mode:** after T4, `shortcut == "MyMode"` (preserved case). Assertion fails.
3. **GREEN** — After the `if/elif/else` block resolves `shortcut`, add:
   ```python
   if shortcut is not None:
       shortcut = shortcut.lower()
   ```
4. Rerun — green. Full suite — green.
5. **Commit:** `feat(hooks-mode): lowercase-normalize shortcuts at parse time`

**Acceptance:** Any mixed-case input (explicit or default-from-name) yields a lowercase `shortcut`. Opt-out (`None`) unaffected.
**Size:** S

---

### T6 — `parse_mode_file`: invalid-character validation + warning

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (add validation step at end of resolution block)
- `modules/hooks-mode/tests/test_parse_shortcut.py`

**Design ref:** §4.1 step 5 (validation), §7.3, §9.1 cases 7, 8, 9, 15

**Sub-steps:**

1. **RED** — Append:
   ```python
   class TestShortcutValidation:
       def test_whitespace_interior_invalid(self, tmp_path, caplog):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: m
                 shortcut: "  my mode  "
                 tools: {safe: []}
                 default_action: block
           """).strip())
           with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
               mode_def = parse_mode_file(f)
           assert mode_def.shortcut is None  # §9.1 case 7
           assert any("not a valid slash-command identifier" in r.message for r in caplog.records)

       def test_slash_invalid(self, tmp_path, caplog):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: m
                 shortcut: "my/mode"
                 tools: {safe: []}
                 default_action: block
           """).strip())
           with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
               mode_def = parse_mode_file(f)
           assert mode_def.shortcut is None  # §9.1 case 8
           assert any("not a valid slash-command identifier" in r.message for r in caplog.records)

       def test_invalid_name_propagates_to_default_shortcut(self, tmp_path, caplog):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: "my mode"
                 tools: {safe: []}
                 default_action: block
           """).strip())
           with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
               mode_def = parse_mode_file(f)
           assert mode_def is not None
           assert mode_def.name == "my mode"  # mode still loads
           assert mode_def.shortcut is None  # §9.1 case 9 — invalid

       def test_leading_digit_invalid(self, tmp_path, caplog):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: m
                 shortcut: "0mode"
                 tools: {safe: []}
                 default_action: block
           """).strip())
           with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
               mode_def = parse_mode_file(f)
           assert mode_def.shortcut is None  # §9.1 case 15
           assert any("not a valid slash-command identifier" in r.message for r in caplog.records)
   ```
2. Run.
   **Expected failure mode:** after T5, `shortcut == "my mode"` / `"my/mode"` / `"0mode"` (lowercased, otherwise intact). Assertions `... is None` fail.
3. **GREEN** — At the end of the resolution block (after the `shortcut.lower()` line from T5), add:
   ```python
   if shortcut is not None and not _is_valid_shortcut(shortcut):
       logger.warning(
           "Mode file %s: shortcut %r is not a valid slash-command identifier "
           "(must match %s); no alias will be registered. "
           "The mode remains activatable via `/mode %s`.",
           file_path, shortcut, _SHORTCUT_PATTERN, resolved_name,
       )
       shortcut = None
   ```
4. Rerun — green. Full suite — green.
5. **Commit:** `feat(hooks-mode): validate shortcut pattern with warn-and-skip on invalid`

**Acceptance:** Any shortcut failing `^[a-z][a-z0-9_-]*$` (after lowercase normalization) becomes `None` with a WARNING log. The mode itself still parses. Case 9 verifies that an invalid `name` does not kill mode loading — only the derived shortcut is dropped.
**Size:** M

---

### T7 — `parse_mode_file`: regression coverage for quoted `"false"` and explicit shortcuts

**Files touched:**
- `modules/hooks-mode/tests/test_parse_shortcut.py` (tests only — no code change expected)

**Design ref:** §9.1 cases 1, 2, 11 (NITPICK-1, Gate 1); §5.2 Note

**Sub-steps:**

1. **RED/GREEN simultaneous (guardrail test).** Append:
   ```python
   class TestShortcutExplicitRegressions:
       def test_explicit_matches_name(self, tmp_path):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: plan
                 shortcut: plan
                 tools: {safe: []}
                 default_action: block
           """).strip())
           assert parse_mode_file(f).shortcut == "plan"  # §9.1 case 1

       def test_explicit_differs_from_name(self, tmp_path):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: plan
                 shortcut: p
                 tools: {safe: []}
                 default_action: block
           """).strip())
           assert parse_mode_file(f).shortcut == "p"  # §9.1 case 2

       def test_quoted_false_is_literal_shortcut_named_false(self, tmp_path):
           f = _write_mode(tmp_path, "m.md", textwrap.dedent("""
               mode:
                 name: m
                 shortcut: "false"
                 tools: {safe: []}
                 default_action: block
           """).strip())
           # YAML string "false" (quoted) is a real string, not a boolean → registers /false.
           # Distinguished from `shortcut: false` (unquoted) which is the opt-out.
           # Design §5.2 Note; §9.1 case 11.
           assert parse_mode_file(f).shortcut == "false"
   ```
2. Run. **Expected:** all three **pass** immediately. This is a known-correct regression guard, not a red-green cycle. Document in the commit body that this task codifies behavior asserted by the existing implementation (T3–T6) but not yet under test.
3. If any of the three fails: **stop**, debug T3–T6 before proceeding. The third case in particular is a likely regression surface if someone later "helpfully" normalizes string-falsy values.
4. **Commit:** `test(hooks-mode): regression coverage for explicit shortcuts and quoted "false"`

**Acceptance:** 3 new tests pass. Full suite green. No code changes.
**Size:** S

---

### T8 — `get_shortcuts`: dict value is `mode_def.name`, not `file.stem`

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (L340–356 — body of `get_shortcuts`)
- `modules/hooks-mode/tests/test_discovery.py` (append to `TestDiscovery` or a new `TestGetShortcuts` class)

**Design ref:** §4.2, §9.2 cases 1, 2, 7 (MINOR-1, Gate 1)

**Sub-steps:**

1. **RED** — Append to `test_discovery.py`:
   ```python
   class TestGetShortcutsNameAsValue:
       def test_default_shortcut_value_is_name(self, tmp_path):
           modes_dir = tmp_path / "modes"
           modes_dir.mkdir()
           (modes_dir / "alpha.md").write_text(textwrap.dedent("""
               ---
               mode:
                 name: alpha
                 tools: {safe: []}
                 default_action: block
               ---
               body
           """).strip() + "\n")
           disc = ModeDiscovery(search_paths=[(modes_dir, "test")])
           disc._coordinator = MagicMock()
           disc._coordinator.capabilities.get.return_value = None
           result = disc.get_shortcuts()
           assert result == {"alpha": "alpha"}  # §9.2 case 1

       def test_stem_differs_from_name(self, tmp_path):
           modes_dir = tmp_path / "modes"
           modes_dir.mkdir()
           (modes_dir / "my_mode.md").write_text(textwrap.dedent("""
               ---
               mode:
                 name: my-mode
                 tools: {safe: []}
                 default_action: block
               ---
               body
           """).strip() + "\n")
           disc = ModeDiscovery(search_paths=[(modes_dir, "test")])
           disc._coordinator = MagicMock()
           disc._coordinator.capabilities.get.return_value = None
           result = disc.get_shortcuts()
           # Key = shortcut (defaults to name, lowercased) = "my-mode"
           # Value = mode_def.name = "my-mode" (NOT "my_mode" stem)
           assert result == {"my-mode": "my-mode"}  # §9.2 case 7 — MINOR-1
   ```
   (If test_discovery.py's setup pattern for `ModeDiscovery` differs, follow its existing fixture style. The existing file already imports `textwrap`, `MagicMock`, and `ModeDiscovery` per the scan at T-baseline.)
2. Run.
   **Expected failure mode:** current L354 assigns `shortcuts[mode_def.shortcut] = name` where `name = mode_file.stem` (L349). For the stem-differs test, this yields `{"my-mode": "my_mode"}` — assertion `{"my-mode": "my-mode"}` fails with `"my_mode" != "my-mode"`.
3. **GREEN** — In `get_shortcuts()` at L354, change the dict write. Full target body of the inner loop branch (L350–354 area):
   ```python
   mode_def = self._cache.get(name) or parse_mode_file(mode_file)
   if mode_def:
       self._cache[name] = mode_def
       if mode_def.shortcut and mode_def.shortcut not in shortcuts:
           shortcuts[mode_def.shortcut] = mode_def.name
   ```
   (Only the last line changes: `name` → `mode_def.name`.)
4. Rerun new tests — green. Rerun full suite — green. Note: this may affect any existing test that asserts on `get_shortcuts()` return values. Inspect such tests and update if they assumed stem semantics; in practice the shipped modes have `name == stem`, so existing assertions should be unaffected.
5. **Commit:** `fix(hooks-mode): store mode_def.name as get_shortcuts value (not file stem)`

**Acceptance:** dict value is `mode_def.name`; diverges correctly from stem when they differ; all existing assertions on shipped modes (which have `name == stem`) still hold.
**Size:** M

---

### T9 — `get_shortcuts`: INFO log on shortcut collision

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (inside `get_shortcuts` loop)
- `modules/hooks-mode/tests/test_discovery.py`

**Design ref:** §4.2 MINOR-1 collision guard, §9.2 cases 4, 5, 6, 8

**Sub-steps:**

1. **RED** — Append:
   ```python
   class TestGetShortcutsCollision:
       def test_collision_across_search_paths_logs_info(self, tmp_path, caplog):
           path_a = tmp_path / "a" / "modes"; path_a.mkdir(parents=True)
           path_b = tmp_path / "b" / "modes"; path_b.mkdir(parents=True)
           for p, n in [(path_a, "review"), (path_b, "review")]:
               (p / "review.md").write_text(textwrap.dedent(f"""
                   ---
                   mode:
                     name: {n}
                     tools: {{safe: []}}
                     default_action: block
                   ---
                   body
               """).strip() + "\n")
           disc = ModeDiscovery(search_paths=[(path_a, "a"), (path_b, "b")])
           disc._coordinator = MagicMock()
           disc._coordinator.capabilities.get.return_value = None
           with caplog.at_level(logging.INFO, logger="amplifier_module_hooks_mode"):
               result = disc.get_shortcuts()
           assert result == {"review": "review"}  # first-wins
           # Names equal -> `existing_name != mode_def.name` is False -> no log emitted.
           # Following §4.2 code (authoritative). §9.2 case 8 variant-1 prose corrected in Rev 2.
           # This test asserts the code behavior: same-name collisions are silent.
           assert not any("collision" in r.message.lower() for r in caplog.records)

       def test_collision_with_different_names_logs_info(self, tmp_path, caplog):
           """Two files claiming the same shortcut key but with different resolved names — the
           genuine collision case. §9.2 case 8 variant 2; MINOR-1 guard."""
           path_a = tmp_path / "a" / "modes"; path_a.mkdir(parents=True)
           path_b = tmp_path / "b" / "modes"; path_b.mkdir(parents=True)
           (path_a / "review.md").write_text(textwrap.dedent("""
               ---
               mode: {name: review, tools: {safe: []}, default_action: block}
               ---
               body
           """).strip() + "\n")
           (path_b / "review.md").write_text(textwrap.dedent("""
               ---
               mode: {name: review-other, shortcut: review, tools: {safe: []}, default_action: block}
               ---
               body
           """).strip() + "\n")
           disc = ModeDiscovery(search_paths=[(path_a, "a"), (path_b, "b")])
           disc._coordinator = MagicMock()
           disc._coordinator.capabilities.get.return_value = None
           with caplog.at_level(logging.INFO, logger="amplifier_module_hooks_mode"):
               result = disc.get_shortcuts()
           assert result == {"review": "review"}  # first-wins by precedence
           assert any("collision" in r.message.lower() and "review-other" in r.message for r in caplog.records)

       def test_explicit_shortcut_collision(self, tmp_path, caplog):
           """Two modes with explicit but conflicting shortcuts. §9.2 case 5."""
           modes = tmp_path / "modes"; modes.mkdir()
           (modes / "a.md").write_text(textwrap.dedent("""
               ---
               mode: {name: alpha, shortcut: x, tools: {safe: []}, default_action: block}
               ---
               body
           """).strip() + "\n")
           (modes / "b.md").write_text(textwrap.dedent("""
               ---
               mode: {name: beta, shortcut: x, tools: {safe: []}, default_action: block}
               ---
               body
           """).strip() + "\n")
           disc = ModeDiscovery(search_paths=[(modes, "test")])
           disc._coordinator = MagicMock()
           disc._coordinator.capabilities.get.return_value = None
           with caplog.at_level(logging.INFO, logger="amplifier_module_hooks_mode"):
               disc.get_shortcuts()
           assert any("collision" in r.message.lower() for r in caplog.records)

       def test_invalid_shortcut_excluded_from_get_shortcuts(self, tmp_path):
           """§9.2 case 6 direct: a mode with an invalid shortcut is absent from get_shortcuts output."""
           # Setup: write a mode file with shortcut: "bad name" (contains space, fails regex)
           # Expected: parse_mode_file sets shortcut=None, get_shortcuts() dict does not contain this mode
           mode_dir = tmp_path / "modes"
           mode_dir.mkdir()
           (mode_dir / "bad.md").write_text(dedent("""\
               ---
               mode:
                 name: bad
                 shortcut: "bad name"
               ---
               """))
           discovery = ModeDiscovery(search_paths=[mode_dir])
           shortcuts = discovery.get_shortcuts()
           assert "bad name" not in shortcuts
           assert "bad" not in shortcuts  # the name itself shouldn't sneak in either
           assert shortcuts == {}  # nothing else is around in this tmp dir
   ```

2. Run.
   **Expected failure mode:** no `collision` log record found in any case (the log statement doesn't exist yet).
3. **GREEN** — Update the `get_shortcuts()` inner branch:
   ```python
   if mode_def.shortcut:
       if mode_def.shortcut in shortcuts:
           existing_name = shortcuts[mode_def.shortcut]
           if existing_name != mode_def.name:
               logger.info(
                   "Shortcut collision: /%s claimed by mode %r (precedence) "
                   "and again by mode %r (skipped). Set `shortcut:` explicitly "
                   "on one of them to disambiguate, or `shortcut: false` to disable.",
                   mode_def.shortcut, existing_name, mode_def.name,
               )
       else:
           shortcuts[mode_def.shortcut] = mode_def.name
   ```
4. Rerun — green. Full suite — green.
5. **Commit:** `feat(hooks-mode): emit INFO log on shortcut collision in get_shortcuts`

**Acceptance:** collision is logged at INFO level when two modes with different resolved `name` values claim the same shortcut key; silent when names match (project override of bundle mode, the common case).
**Size:** M

---

### T10 — Integration: end-to-end fake-bundle `get_shortcuts`

**Files touched:**
- `modules/hooks-mode/tests/test_parse_shortcut.py` (append at bottom — or a new `test_integration_shortcut.py` if preferred)

**Design ref:** §9.3

**Sub-steps:**

1. **RED/GREEN (guardrail).** Append:
   ```python
   class TestIntegrationFakeBundle:
       def test_fake_bundle_layout(self, tmp_path):
           """§9.3 integration: three modes — omitted / opt-out / explicit."""
           modes = tmp_path / "fake-bundle" / "modes"
           modes.mkdir(parents=True)
           (modes / "alpha.md").write_text(textwrap.dedent("""
               ---
               mode: {name: alpha, tools: {safe: []}, default_action: block}
               ---
               body
           """).strip() + "\n")
           (modes / "beta.md").write_text(textwrap.dedent("""
               ---
               mode: {name: beta, shortcut: false, tools: {safe: []}, default_action: block}
               ---
               body
           """).strip() + "\n")
           (modes / "gamma.md").write_text(textwrap.dedent("""
               ---
               mode: {name: gamma, shortcut: g, tools: {safe: []}, default_action: block}
               ---
               body
           """).strip() + "\n")
           disc = ModeDiscovery(search_paths=[(modes, "test")])
           disc._coordinator = MagicMock()
           disc._coordinator.capabilities.get.return_value = None
           result = disc.get_shortcuts()
           assert result == {"alpha": "alpha", "g": "gamma"}  # no `beta` key
   ```
2. Run. **Expected:** passes immediately (all prerequisite behavior landed in T2/T3/T8).
3. If fails: stop and reconcile — indicates T2/T3/T8 is incomplete.
4. **Commit:** `test(hooks-mode): integration test for default/opt-out/explicit shortcut scenarios`

**Acceptance:** the integration test passes without any further code change.
**Size:** S

---

### T11 — Documentation-parity regression test (strengthened M1)

**Files touched:**
- `modules/hooks-mode/tests/test_docs_parity.py` (NEW)

**Design ref:** §9.6 (M1, Gate 1)

**Sub-steps:**

1. **RED** — Create `test_docs_parity.py`:
   ```python
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


   @pytest.mark.parametrize("relpath", [
       "context/modes-instructions.md",
       "README.md",
   ])
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
   ```
2. Run.
   **Expected failure mode:** `context/modes-instructions.md` currently does not contain `shortcut` or `default` or `false` — the parametrized case for that file fails with `missing: ['shortcut', 'default', 'false']` (or similar, depending on current content). The README case may pass partially (it currently mentions `shortcut` and likely `default` in other contexts) — verify the exact failure list by running.
3. **GREEN DEFERRED.** Do **not** update docs in this task. The test is intentionally left red until T12/T13 land. Mark the task as "test infrastructure complete, docs gating in place."
4. **Commit:** `test(hooks-mode): add documentation-parity regression for shortcut semantics`

**Acceptance:** the test file exists, runs, and produces the predicted failure list. Full suite shows this test as `FAILED` with a clear message. (Subsequent doc tasks drive it green.)
**Size:** S

---

### T12 — Update `context/modes-instructions.md`: authoritative agent-facing documentation

**Files touched:**
- `context/modes-instructions.md`

**Design ref:** §8 first bullet (non-negotiable)

**Mode:** Non-TDD (doc change); driven by T11's parametrized assertion.

**Sub-steps:**

1. Read the current file. Locate the "Custom Modes" / "Mode Configuration" section (~L44).
2. Add a "Mode Configuration" subsection documenting the frontmatter fields. Must include:
   - The `name` field (required in practice; defaults to filename stem).
   - The `description` field.
   - The `shortcut` field — mark as optional; state that **it defaults to the mode's `name`** (lowercased) when omitted; state that `shortcut: false` disables it; state that shortcuts must match `^[a-z][a-z0-9_-]*$` after lowercasing, or a warning is logged and no alias registered.
   - The `tools.{safe,warn,confirm,block}` lists.
   - The `default_action` field.
3. Include the **quoted-`"false"` caveat** (NITPICK-1): `shortcut: false` (unquoted boolean) is opt-out; `shortcut: "false"` (quoted string) registers `/false`.
4. Include the **Known Limitations** note (MINOR-3): modes named the same as built-in CLI commands (`help`, `mode`, `modes`, `exit`, `quit`) will have their default slash alias silently overridden by the CLI dispatch; remain activatable via `/mode <name>`; to get a working alias in that case, set `shortcut:` explicitly to a non-reserved value.
5. Include **third-party naming guidance** (m4): prefer descriptive, unique names (e.g. `systems-design`, not `design`; `perf-audit`, not `perf`) — first-load wins silently on collision, and the second bundle's shortcut is dropped with an INFO log.
6. **Verification:** run `pytest modules/hooks-mode/tests/test_docs_parity.py::test_documentation_describes_shortcut_semantics -q`. The `context/modes-instructions.md` parametrization should now pass. The README one may still fail until T13.
7. Manually skim the updated section for clarity. Confirm it can stand as the sole agent-facing reference for mode authoring.
8. **Commit:** `docs(modes): document shortcut field and semantics in modes-instructions.md`

**Acceptance:** the docs-parity test's `context/modes-instructions.md` parametrization passes; all four required terms (`shortcut`, `default`, `name`, `false`) appear (case-insensitive); the three callouts (quoted-`"false"`, known-limitation, naming-guidance) are present verbatim or in substance.
**Size:** M

---

### T13 — Update `README.md`: Mode Configuration table, Commands table, Third-Party section, Known Limitations, quoted-`"false"`

**Files touched:**
- `README.md`

**Design ref:** §8 second bullet

**Mode:** Non-TDD (doc change); driven by T11's README parametrization + manual verification.

**Sub-steps:**

1. Open `README.md`. Locate the "Mode Configuration" table (~L126–137).
2. **Replace** the existing `shortcut` row with:
   > `| shortcut | No (defaults to name) | Slash-command alias. Defaults to the mode's name (lowercased). Set to `false` to disable. Must match `^[a-z][a-z0-9_-]*$` after lowercasing; invalid values log a warning and register no alias. |`
3. Locate the "Commands" table. **Replace** the row referencing `/plan, /explore, /careful` with (per n2):
   > `| /<mode-name> | Auto-generated shortcut for each mode (use `shortcut: false` to disable, or set `shortcut:` to override) |`
4. In the "Creating Custom Modes" example, add an in-line comment next to the `shortcut:` line:
   > `# shortcut: mymode   # Optional; defaults to `name`. Use `shortcut: false` to disable.`
5. Add (or create) a **"Known Limitations"** callout:
   > Modes named the same as built-in CLI commands (`help`, `mode`, `modes`, `exit`, `quit`) will have their default slash alias silently overridden by the CLI; set `shortcut:` explicitly to a non-reserved value.
6. Add the **quoted-`"false"` caveat** adjacent to opt-out documentation:
   > `shortcut: false` (YAML boolean) disables the alias. `shortcut: "false"` (quoted string) is a shortcut literally named `false` and registers `/false`. Use the unquoted boolean form to disable.
7. In the **"Third-Party Bundle Modes"** section (create if absent, near the end of the README), add the naming guidance (m4): prefer descriptive, unique names — first-load wins silently on collision; losing shortcuts are dropped with an INFO log in `get_shortcuts()`.
8. **Verification:**
   - Run `pytest modules/hooks-mode/tests/test_docs_parity.py -q` — both parametrizations should now pass.
   - Visually inspect the rendered README in the PR preview mentally: tables still parse as markdown tables; callouts are visually distinct.
9. **Commit:** `docs(modes): update README shortcut documentation, Commands table, and Known Limitations`

**Acceptance:** T11's full parametrized test passes (both parameters green); all design §8 bullets for README are present; markdown tables remain valid.
**Size:** M

---

### T14 — Update `bundle.md`: Custom Mode example + fix stale `/mode review` at L25

**Files touched:**
- `bundle.md`

**Design ref:** §8 third bullet, m5 (Gate 1)

**Mode:** Non-TDD (doc change); verify by grep + manual read.

**Sub-steps:**

1. Open `bundle.md`. Scroll to L25 (the Usage section around L20–27).
2. **Replace** the stale `/mode review     # Switch to review mode` line with:
   > `/mode plan       # Switch to plan mode`
   (or `/mode careful` — either is a real shipped built-in; `plan` is preferred for consistency with the line above.)

   *Judgment call:* the design specifies "`/mode plan` (or `/mode careful`)." The line immediately above already uses `/mode plan`, so substituting a duplicate is redundant. The implementer may instead remove the stale line outright OR substitute `/mode careful`. Either satisfies m5. Document the choice in the commit message.
3. Locate the "Creating Custom Modes" example frontmatter (L39–54).
4. Add an in-line comment next to the `shortcut: mymode` line (L44):
   > `shortcut: mymode   # Optional; defaults to `name`. Use `shortcut: false` to disable.`
5. **Verification:** `grep -n "/mode review" bundle.md` should return no matches. `grep -n "shortcut" bundle.md` should show the annotated line.
6. **Commit:** `docs(bundle): fix stale /mode review example and annotate shortcut as optional`

**Acceptance:** no `/mode review` text remains; `shortcut:` in the example is explicitly annotated as optional with default and opt-out behavior noted.
**Size:** S

---

### T15 — Update `parse_mode_file` docstring (m3, Gate 1)

**Files touched:**
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (docstring at L47–L65)

**Design ref:** §8 fourth bullet, m3 (Gate 1)

**Mode:** Non-TDD (doc change); verify by re-reading.

**Sub-steps:**

1. Open `__init__.py`. Locate the `parse_mode_file` docstring (L47–L65).
2. **Revise** to:
   - State that `shortcut:` is **optional** — defaults to the mode's `name` (lowercased) when omitted.
   - Show the opt-out form `shortcut: false` in a second YAML example block (inline in the docstring).
   - Remove any wording that implies the field must be set.
   - Add: "Shortcuts are lowercase-normalized at parse time and validated against `^[a-z][a-z0-9_-]*$`; invalid values log a warning and are dropped (the mode remains activatable via `/mode <name>`)."
3. Re-check: the sample frontmatter in the docstring (currently shows `shortcut: plan`) should either keep that line with a comment marking it optional, or show two example blocks (one with an explicit shortcut, one with `shortcut: false`).
4. **Verification:** `grep -n "shortcut" modules/hooks-mode/amplifier_module_hooks_mode/__init__.py | head -20` should show both the docstring mention and the implementation references. Manual read-through confirms the docstring matches design §4.1 semantics.
5. **Commit:** `docs(hooks-mode): update parse_mode_file docstring to reflect shortcut semantics`

**Acceptance:** the docstring no longer implies `shortcut:` is required; explicitly documents default-from-name, opt-out syntax, lowercasing, and validation.
**Size:** S

---

### T16 — Add changelog entry

**Files touched:**
- `CHANGELOG.md` (NEW if it doesn't exist; otherwise append to the "Unreleased" section)

**Design ref:** §8 fifth bullet

**Mode:** Non-TDD (doc change).

**Sub-steps:**

1. Check for an existing changelog: `ls amplifier-bundle-modes/CHANGELOG.md` — if present, append to the current "Unreleased" / next-version section. If absent, create one following the Keep-a-Changelog format.
2. Add the entry:
   ```markdown
   ## [Unreleased]

   ### Changed
   - `shortcut:` in mode frontmatter now defaults to the mode's `name` when omitted.
     Set `shortcut: false` to disable. Shortcuts are lowercased at parse time and validated
     against `^[a-z][a-z0-9_-]*$`; invalid values log a warning and register no alias (the
     mode remains activatable via `/mode <name>`). Modes that previously lacked a slash
     alias due to the missing field will now gain one; to restore the prior behavior, add
     an explicit `shortcut: false`. (Fixes silent failure mode where `/<mode-name>`
     returned `"Unknown command"`.)

   ### Known limitations
   - Modes whose `name` matches a built-in CLI command (`help`, `mode`, `modes`, `exit`,
     `quit`, etc.) will register a default shortcut that is silently overridden by the
     CLI's command dispatch. These modes remain activatable via `/mode <name>`. To give
     such a mode a working slash alias, set `shortcut:` explicitly to a non-reserved value.

   ### Notes
   - `shortcut: false` (YAML boolean) is opt-out. `shortcut: "false"` (quoted string) is a
     regular shortcut literally named `false` and will register `/false`. Use the
     unquoted boolean form to disable.
   ```
3. **Verification:** `grep -c "shortcut" CHANGELOG.md` ≥ 4.
4. **Commit:** `docs: changelog entry for shortcut default-to-name change`

**Acceptance:** changelog entry exists, covers the three required sub-sections (Changed, Known limitations, Notes).
**Size:** S

---

### T17 — Verify shipped modes unchanged and still activate correctly

**Files touched:**
- `modules/hooks-mode/tests/test_parse_shortcut.py` (append a regression class)

**Design ref:** §8 sixth bullet (shipped modes remain as in-repo reference)

**Sub-steps:**

1. **RED/GREEN guardrail.** Append:
   ```python
   import pathlib

   BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[3]

   class TestShippedModesUnchanged:
       """§8: the three shipped modes (careful, plan, explore) keep explicit shortcuts
       as in-repo reference. This test prevents an accidental removal."""

       @pytest.mark.parametrize("mode_name,expected_shortcut", [
           ("careful", "careful"),
           ("plan", "plan"),
           ("explore", "explore"),
       ])
       def test_shipped_mode_shortcut(self, mode_name: str, expected_shortcut: str) -> None:
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
   ```
   (Import `pytest` at the top of the file if not already present.)
2. Run. **Expected:** passes immediately (shipped modes currently have explicit `shortcut:`).
3. If any fails: the shipped modes were inadvertently touched earlier. Revert those changes.
4. **Commit:** `test(hooks-mode): lock in shipped modes as reference examples with explicit shortcut`

**Acceptance:** 4 new tests pass. Full suite green.
**Size:** S

---

### T18 — Final verification checkpoint

**Files touched:** (none — verification only)

**Design ref:** §9 overall

**Sub-steps:**

1. Run the full module suite: `cd modules/hooks-mode && uv run pytest -v`.
2. Confirm test count = baseline + (sum of new tests across T1–T11, T17). Expected additions: ~25–30 new tests.
3. Confirm all pass, including:
   - `test_parse_shortcut.py` (all classes from T1, T2, T3, T4, T5, T6, T7, T10, T17)
   - `test_discovery.py` (new `TestGetShortcutsNameAsValue` from T8 and `TestGetShortcutsCollision` from T9)
   - `test_docs_parity.py` (both parametrizations from T11 — T12 and T13 drive them green)
4. Run lint/format on the changed Python file:
   - `python_check paths=["modules/hooks-mode/amplifier_module_hooks_mode/__init__.py", "modules/hooks-mode/tests/test_parse_shortcut.py", "modules/hooks-mode/tests/test_docs_parity.py", "modules/hooks-mode/tests/test_discovery.py"]`
   - Fix any formatting/lint issues before proceeding.
5. Verify git log on `feat/default-shortcut-to-name`: ~17 commits (T1–T17), each a conventional-commit message, each atomic.
6. Run a doc-parity grep manually:
   - `grep -i "shortcut" context/modes-instructions.md` — expect multiple hits, including `default`, `false`, `name`.
   - `grep -i "shortcut" README.md` — same.
   - `grep -i "/mode review" bundle.md` — expect no hits.
7. Mark ready for DTU handoff (§10 below).

**Acceptance:** all tests green; lint clean; no grep regressions; branch is a linear series of atomic commits.
**Size:** S

---

## 4. Task dependency graph

All tasks are executed sequentially by a single implementer agent. Logical dependencies (what must precede what) are shown below; items at the same indentation level are logically independent but still executed in listed order.

```
P0 (branch, baseline green)
 ├─ T1  (helper + regex constant)
 │   └─ T2  (default-from-name)
 │       └─ T3  (opt-out branch)
 │           └─ T4  (YAML boolean guard)
 │               └─ T5  (lowercase normalize)
 │                   └─ T6  (validation + warn)
 │                       └─ T7  (explicit-shortcut regressions — uses all parse behavior)
 │                           └─ T10 (integration — depends on T2, T3, T8)
 ├─ T8  (get_shortcuts: dict value = mode_def.name)     ← logically independent of T1–T7
 │   └─ T9  (collision INFO log)
 │       └─ T10 (integration)
 ├─ T11 (docs-parity test file — independent of code changes)
 │   ├─ T12 (modes-instructions.md)  ← drives T11 param-1 green
 │   └─ T13 (README.md)              ← drives T11 param-2 green
 ├─ T14 (bundle.md)                   ← independent
 ├─ T15 (docstring)                   ← independent, but easier to do after parse_mode_file landed (T6)
 ├─ T16 (changelog)                   ← independent
 └─ T17 (shipped-modes lock)          ← independent, should be run any time
     └─ T18 (final verification checkpoint)
```

**Logical parallelism (for reviewer's context only, not used):** T8/T9 could be done before or interleaved with T1–T7 without issue. T11–T17 are independent of each other. The sequential execution in the numbered order keeps the implementer's context minimal and the diffs clean.

---

## 5. Test matrix cross-reference

Every design-§9 test case is covered. Each row below maps one design case to the task that introduces the test.

### 5.1 Design §9.1 — `parse_mode_file` cases

| # | Case | Task |
|---|------|------|
| 1 | `shortcut: plan` → `"plan"` | T7 (`test_explicit_matches_name`) |
| 2 | `shortcut: p` (different from name) → `"p"` | T7 (`test_explicit_differs_from_name`) |
| 3 | key omitted, `name: explore` → `"explore"` | T2 (`test_key_omitted_defaults_to_name`) |
| 4 | `shortcut: false` → `None` | T3 (`test_false_opts_out`) |
| 5 | `shortcut: null` → `None` | T3 (`test_null_tolerated_as_opt_out`) |
| 6 | `shortcut: ""` → `None` | T3 (`test_empty_string_tolerated_as_opt_out`) |
| 7 | `shortcut: "  my mode  "` → `None` + warn | T6 (`test_whitespace_interior_invalid`) |
| 8 | `shortcut: "my/mode"` → `None` + warn | T6 (`test_slash_invalid`) |
| 9 | key omitted, `name: "my mode"` → `None`; mode still parses | T6 (`test_invalid_name_propagates_to_default_shortcut`) |
| 10 | key omitted, `name` also omitted → stem | T2 (`test_key_omitted_and_name_omitted_defaults_to_stem`) |
| 11 | `shortcut: "false"` (quoted) → `"false"` | T7 (`test_quoted_false_is_literal_shortcut_named_false`) |
| 12a | `shortcut: yes` → default + warn | T4 (`test_yaml_yes_warns_and_defaults`) |
| 12b | `shortcut: true` → default + warn | T4 (`test_yaml_true_warns_and_defaults`) |
| 12c | `shortcut: on` → default + warn | T4 (`test_yaml_on_warns_and_defaults`) |
| 13 | `name: MyMode`, no shortcut → `"mymode"` | T5 (`test_name_mixed_case_lowercased_in_default`) |
| 14 | `shortcut: MyMode` → `"mymode"` | T5 (`test_explicit_mixed_case_lowercased`) |
| 15 | `shortcut: "0mode"` → `None` + warn | T6 (`test_leading_digit_invalid`) |

*Bonus:* §7.5 (whitespace-only opt-out) → T3 (`test_whitespace_only_string_opts_out`).

### 5.2 Design §9.2 — `get_shortcuts` cases

| # | Case | Task |
|---|------|------|
| 1 | Single mode, no field → `{"<name>": "<name>"}` | T8 (`test_default_shortcut_value_is_name`) |
| 2 | Single mode, explicit field → `{"<explicit>": "<name>"}` | Covered implicitly by T10 (`gamma`: `{"g": "gamma"}`) |
| 3 | Single mode, opt-out → `{}` | T10 (`beta` with `shortcut: false` absent from result) |
| 4 | Two modes across search paths, same default shortcut → first-wins + INFO (names equal → no log per design §4.2 code; names different → log) | T9 (`test_collision_across_search_paths_logs_info`, `test_collision_with_different_names_logs_info`) |
| 5 | Two modes with explicit conflicting shortcuts | T9 (`test_explicit_shortcut_collision`) |
| 6 | Mode with invalid shortcut → excluded | T9 (`test_invalid_shortcut_excluded_from_get_shortcuts`) — direct end-to-end: invalid shortcut in `parse_mode_file` → `None` → absent from `get_shortcuts()` output |
| 7 | `my_mode.md` + YAML `name: my-mode` | T8 (`test_stem_differs_from_name`) |
| 8 | Two files both `name: my-mode`, same key / different key | T9 (both variants in `test_collision_*` tests) |

### 5.3 Design §9.3 — integration

| Case | Task |
|------|------|
| Fake bundle: alpha (omitted), beta (opt-out), gamma (explicit) | T10 (`test_fake_bundle_layout`) |

### 5.4 Design §9.6 — documentation parity regression

| Case | Task |
|------|------|
| `context/modes-instructions.md` contains `shortcut`, `default`, `name`, `false` | T11 (parametrized, driven green by T12) |
| `README.md` contains same four terms | T11 (parametrized, driven green by T13) |

### 5.5 Design §9.4 — DTU end-to-end

| Case | Task |
|------|------|
| Fresh session, `/modes` lists probe | DTU pipeline stage (§10 below) |
| `/probe` activates mode | DTU |
| `/mode probe` works (regression) | DTU |
| Second probe with `shortcut: false` — `/probe2` → `"Unknown command"` | DTU |

**Every design-§9 test case is covered.**

---

## 6. Documentation change tasks (summary)

Already itemized as T12–T17 above. Summary for CoE review:

| Task | File | Mode | Drives test green |
|------|------|------|--------------------|
| T12 | `context/modes-instructions.md` | Doc | T11 param-1 |
| T13 | `README.md` | Doc | T11 param-2 |
| T14 | `bundle.md` | Doc | (grep verification) |
| T15 | `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (docstring only) | Doc | (manual read) |
| T16 | `CHANGELOG.md` | Doc | (grep verification) |
| T17 | `modules/hooks-mode/tests/test_parse_shortcut.py` (shipped-modes lock) | Test | Self-green on landing |

---

## 7. Verification checkpoints

Three structural checkpoints embedded in the flow, plus the final T18 gate.

**Checkpoint A — after T7 (parse path complete):**
- Run `pytest modules/hooks-mode/tests/test_parse_shortcut.py -v`.
- Expect: all TestShortcut* classes green.
- Expect: full module suite green (T8/T9 changes not yet landed; prior test_discovery.py tests unchanged).

**Checkpoint B — after T10 (discovery path complete):**
- Run `pytest modules/hooks-mode/tests/ -v`.
- Expect: all parse and discovery tests green.
- `test_docs_parity.py` intentionally FAILS both parametrizations (T11 in place, T12/T13 not yet).

**Checkpoint C — after T17 (docs complete):**
- Run `pytest modules/hooks-mode/tests/ -v`.
- Expect: **everything** green.
- Run `grep -i "shortcut" context/modes-instructions.md README.md bundle.md CHANGELOG.md` — expect multiple hits in each.
- Run `grep -n "/mode review" bundle.md` — expect zero hits.

**Gate — T18** (as documented above).

---

## 8. Rollback plan

If during execution a test or finding reveals a design flaw:

1. **Scope-contained rollback (single task):**
   ```
   git reset --hard HEAD~1     # undoes the most recent task commit
   ```
   Re-assess the red-phase failure mode. If the design is incompatible with the observed behavior, escalate to zen-architect with a concrete findings report; do **not** patch the design silently.

2. **Feature abandonment (full rollback):**
   ```
   git checkout main
   git branch -D feat/default-shortcut-to-name
   ```
   All working-tree changes (submodule) are confined to the feature branch; no upstream commit was made; no publish happened. Submodule stays at its prior `HEAD` on `main`.

3. **Partial landing (land code, hold docs):** unsupported by this plan — docs parity is non-negotiable per design §R7 (M1). The documentation-parity regression test will block T18 until docs are in place. Do **not** bypass by skipping the test.

4. **Design ambiguity discovered mid-implementation:**
   - The design §9.2 case 8 "variant 1" prose discrepancy (previously noted as a judgment call in T9) is resolved: design doc is now Rev 2 with the prose corrected to match the §4.2 code. No known ambiguities remain. If the implementer encounters any ambiguity, stop at the current task, document it in a comment on this plan, and request zen-architect review before proceeding. Do not guess.

---

## 9. Handoff to DTU test

After T18 closes:

**Preconditions the DTU validator will verify:**
- Branch `feat/default-shortcut-to-name` exists locally and at the current submodule HEAD.
- `pytest` is green (documented from T18).
- All five doc files updated (`context/modes-instructions.md`, `README.md`, `bundle.md`, the Python docstring, `CHANGELOG.md`).

**DTU pipeline stage (handled by `amplifier-tester` bundle, not this plan):**

1. `amplifier-tester:setup-digital-twin` launches a fresh DTU with:
   - Amplifier installed from the tip of the workspace.
   - `amplifier-bundle-modes` composed from the `feat/default-shortcut-to-name` branch.
   - A minimal probe bundle containing two mode files:
     - `modes/probe.md` — no `shortcut:` field, `name: probe`.
     - `modes/probe2.md` — `shortcut: false`, `name: probe2`.
2. `amplifier-tester:validator` executes the four §9.4 assertions:
   - Assertion 1: `/modes` output contains `probe` and `probe2`.
   - Assertion 2: `/probe` activates the mode (prompt reflects mode activation, no `"Unknown command"`).
   - Assertion 3: `/mode probe` continues to work (regression).
   - Assertion 4: `/probe2` returns `"Unknown command"`; `/mode probe2` works.
3. On DTU pass → handoff to `foundation:git-ops` → opens PR against `microsoft/amplifier-bundle-modes`. The version bump in `pyproject.toml` (minor bump per design §A6) is `git-ops`'s responsibility at PR time; the implementer does not need a task for it.
4. On DTU fail → capture failure transcript, return to this branch, delegate root-cause investigation to `foundation:bug-hunter` with the DTU artifacts as input. Do not open a PR.

**Artifacts for DTU stage:**
- Probe bundle YAML (templated in §9.4 of design, ready to drop into DTU profile).
- Baseline Amplifier install version (TBD by setup-digital-twin).
- Expected CLI output snippets (listed in §9.4 of design).

---

## 10. Judgment calls (beyond the design)

Areas where the plan had to resolve ambiguity or make sequencing choices not explicitly decided in the design:

1. **Helper extraction (T1).** The design at §4.1 uses `_is_valid_shortcut(...)` and `_SHORTCUT_PATTERN` in its pseudocode but does not mandate them as named symbols. The plan codifies them as a module-private helper + constant, enabling T1 to be a cleanly TDD'd standalone unit. This is a minor design freedom; the helper could be inlined, but the cost is higher-coupled tests and worse isolation of the regex from the resolution flow.

2. **Task ordering for parse_mode_file (T2–T7).** The design specifies seven semantic behaviors inside a single block. The plan decomposes them into a layered series — one behavior per commit, one red/green per behavior. The tradeoff: each red-phase observes an **intermediate** failure mode, not the final-state failure mode. Each task documents its expected failure explicitly to keep the discipline honest. The alternative (write all tests, then write all code) is more conventional but violates "observe the failure before making the fix" per task and reduces traceability.

3. **Test file organization.** The plan creates a new `test_parse_shortcut.py` rather than bloating `test_discovery.py`. `test_discovery.py` retains all `ModeDiscovery`-level tests (T8, T9). A new `test_docs_parity.py` isolates the doc-parity regression. This mirrors the module's existing organization (one test file per concern).

4. **Design §9.2 case 8 variant-1 interpretation (resolved).** The design text in Rev 1 said "False → collision IS logged" — a prose inversion. The §4.2 code (`if existing_name != mode_def.name: logger.info(...)`) was always authoritative: names-equal → NO log. The design doc is now Rev 2 with the prose corrected to match. T9's variant-1 test and T9's inline comment reflect the correct behavior. No ambiguity remains; this judgment call is closed.

5. **`bundle.md` L25 replacement wording.** Design specifies "`/mode plan` (or `/mode careful`)"; the line immediately above already uses `/mode plan`. The plan notes the implementer may use `/mode careful` or remove the stale line, to avoid duplicate content. Either satisfies m5; choice goes in the commit message.

6. **Shipped-modes lock (T17).** §8 sixth bullet says "Decision: leave them as-is; they are the canonical reference" but does not specify a test. The plan adds T17 as a regression guard so a future refactor removing those fields (perhaps "helpfully" relying on the new default) would fail loudly. Purely additive.

7. **Test count targets.** The plan projects ~25–30 new tests. If the actual count diverges materially (e.g. <20 or >40), that's a signal worth CoE attention — it would suggest either missed coverage or over-parameterization.

---

## 11. Plan completeness checklist (for Gate 2 CoE)

- [x] Every design-§9 test case mapped to a specific task creating the test (§5).
- [x] Every design-§8 doc change mapped to a task (T12–T17).
- [x] All four headline decisions (opt-out `false`, parse-time locus, regex+warn, first-wins+INFO) traced to specific tasks.
- [x] All Gate-1 refinements (M1, M2, m3, m4, m5, MINOR-1, MINOR-2, MINOR-3, NITPICK-1, NITPICK-4) have a task or explicit inline citation.
- [x] TDD discipline enforced per-task (RED → GREEN → commit) with observed-failure predictions.
- [x] Task size budget respected (all S or M; no L tasks).
- [x] No task modifies more than 2–3 files.
- [x] Rollback plan explicit and mechanical.
- [x] DTU handoff preconditions enumerated; DTU stage is explicitly separate from this plan.
- [x] Judgment calls (§10) disclosed for reviewer scrutiny.
