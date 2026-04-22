# Design: Default `shortcut` to the mode's `name` when unset

**Status:** Rev 2 — Gate 2 CoE cleanup applied; design approved
**Author:** zen-architect (ANALYZE + ARCHITECT mode)
**Scope:** `amplifier-bundle-modes` (bundle-level change; no kernel changes)
**Related incident:** `/systems-design` returned `"Unknown command"` despite the mode being discoverable via `/modes` and activatable via `/mode systems-design`. Root cause: mode files in `amplifier-bundle-systems-design/modes/` omitted the `shortcut:` frontmatter field.

### Revision history

- **Rev 0** — Initial draft (Gate 1 submission).
- **Rev 1 (Gate 1 CoE revisions)** — addressed foundation-expert M1/M2/m3/m4/m5/n1/n2 and core-expert MINOR-1/2/3 and NITPICK-1/2/3/4. Headline decisions unchanged (opt-out = `shortcut: false`; change locus = `parse_mode_file`; validation = regex+WARN+skip; collision = first-wins+INFO). Refinements:
  - YAML boolean trap closed: `shortcut: yes`/`true`/`on` now guarded before string coercion (M2).
  - Regression test for `context/modes-instructions.md` strengthened to multi-term assertion (M1).
  - Collision-guard compares `mode_def.name` (the authoritative identity), not `file.stem`; dict value is `mode_def.name` (MINOR-1).
  - Shortcuts normalized to lowercase at parse time; regex tightened to lowercase-only (MINOR-2).
  - Known-limitation note added for modes named the same as built-in CLI commands (MINOR-3).
  - Docstring update, third-party naming guidance, stale `bundle.md` example, quoted-`"false"` note, README row wording, and §10.3 lead-argument reorder (m3/m4/m5/n1/n2, NITPICK-1/2/3/4).
- **Rev 2 (Gate 2 CoE fix)** — §9.2 case 8 variant-1 prose corrected to match §4.2 code (names-equal → no log). No code decisions changed.

---

## 1. Problem framing

The `shortcut:` field in a mode file's YAML frontmatter is what causes the CLI to register a direct slash-command alias (e.g. `/plan`, `/explore`). The field is:

- **Documented as optional** (`README.md:132` — "No" in the Required column).
- **Not mentioned at all** in the agent-facing doc (`context/modes-instructions.md:44` — "YAML frontmatter with a `mode:` section defining name, description, and tool policies").
- **Effectively required** in practice: without it, users cannot invoke the mode via its natural `/name` command and must fall back to the more verbose `/mode <name>` form.

The failure mode is silent. `/modes` still lists the mode (different code path), `/mode <name>` still activates it, and no warning is emitted anywhere. The author only learns their mode is half-broken when a user reports "`/my-mode` says Unknown command."

Authoring LLMs (the common case for third-party mode creation) consult `modes-instructions.md`, see no mention of `shortcut:`, and produce shortcut-less files by default. This is how papayne's `systems-design` bundle shipped broken, and it is the pattern any future third-party bundle will follow unless we close the gap.

## 2. Explicit assumptions

- **A1.** The primary author of new mode files, going forward, is an LLM consulting `modes-instructions.md`. Design must optimize for the default-when-no-guidance path, not only for the careful hand-written path.
- **A2.** Mode file discovery, loading, and shortcut registration all happen at session startup before any user command dispatch. `parse_mode_file()` and `ModeDiscovery.get_shortcuts()` are the single chokepoints.
- **A3.** The dispatch order in the CLI is fixed: built-in `COMMANDS` first, then `MODE_SHORTCUTS`. This ordering does not need to change for this design to work. (See `amplifier_app_cli/main.py:273` for `COMMANDS`, `main.py:361` for the `MODE_SHORTCUTS` check.)
- **A4.** Mode `name` values in real use are conventional identifiers — lowercase letters, digits, hyphens, underscores. All shipped examples match this (`careful`, `plan`, `explore`, `systems-design`, `brainstorm`, `debug`, `systems-design-review`).
- **A5.** No downstream tooling reads `mode_def.shortcut` other than `ModeDiscovery.get_shortcuts()` and (indirectly via that method) the CLI's `CommandProcessor`. A grep of the bundle confirms `shortcut` is a leaf field with exactly one producer (`parse_mode_file` at `__init__.py:97`) and one consumer (`get_shortcuts` at `__init__.py:353`).
- **A6.** Changing the default is acceptable as a minor version bump of the bundle. There is no SLA that "a mode without `shortcut:` has no slash alias" — that behavior is undocumented and counter to user expectation.

## 3. Current behavior

**Parse** — `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:94–106`

```python
return ModeDefinition(
    name=mode_config.get("name", file_path.stem),       # L95: defaults to filename stem
    description=mode_config.get("description", ""),      # L96
    shortcut=mode_config.get("shortcut"),                # L97: None if omitted
    ...
)
```

- `shortcut` defaults to `None` when the key is omitted. There is no sanitization, no validation, no warning.
- `name` falls back to `file_path.stem` if the author omitted it. Every shipped mode sets it explicitly.

**Collect** — `__init__.py:340–356` (`ModeDiscovery.get_shortcuts`)

```python
def get_shortcuts(self) -> dict[str, str]:
    self._ensure_bundle_discovery()
    shortcuts: dict[str, str] = {}
    for base_path, _source_label in self._search_paths:
        if not base_path.exists():
            continue
        for mode_file in base_path.glob("*.md"):
            name = mode_file.stem
            mode_def = self._cache.get(name) or parse_mode_file(mode_file)
            if mode_def:
                self._cache[name] = mode_def
                if mode_def.shortcut and mode_def.shortcut not in shortcuts:
                    shortcuts[mode_def.shortcut] = name
    return shortcuts
```

- **Truthy gate** at L353: falsy (`None`, `False`, `""`) means "no shortcut registered."
- **First-wins** at L353: if two modes claim the same shortcut, the first one encountered (ordered by `_search_paths` precedence, then filesystem glob order within each path) wins silently. No log, no warning.
- Note: `name` here (L349) is the **filename stem**, used only as the dict *value*. The shortcut *key* is strictly `mode_def.shortcut`. This matters for the design: if we default from name, we must default from `mode_def.name` (the authoritative field) not `file_path.stem` (convention but not contract). In practice they agree for shipped modes, but the file's `mode.name` is the contract.

**Register** — CLI `amplifier_app_cli/main.py:314, 325, 327–333, 361`

```
MODE_SHORTCUTS: dict[str, str] = {}          # L314 class attr
self._populate_mode_shortcuts()              # L325 in __init__
def _populate_mode_shortcuts(self) -> None:  # L327
    ...
    CommandProcessor.MODE_SHORTCUTS.update(shortcuts)   # L333
...
if shortcut_name in self.MODE_SHORTCUTS:     # L361 dispatch check
    ...
return "unknown_command", {"command": command}   # L374 fall-through
```

**Listing** — `__init__.py:321–338` (`list_modes`) — iterates the same paths but does **not** consult `shortcut`. That is why `/modes` showed `systems-design` while `/systems-design` did not work.

**Summary of the current invariants this design must preserve or justify changing:**

| Invariant | Current behavior | Touched by this design? |
|---|---|---|
| `mode.name` required (in practice); defaults to filename stem if missing | L95 | No |
| `shortcut` optional; `None` → no alias | L97, L353 | **Yes — changing the default** |
| First-wins collision across search paths | L353 | **Tightening — adding a warning log** |
| No name/shortcut character validation | (none) | **Adding — validate at parse time, warn, skip invalid** |
| `list_modes` independent of `shortcut` | L321–338 | No |
| Dispatch order: `COMMANDS` before `MODE_SHORTCUTS` | `main.py:273, 361` | No |

## 4. Proposed change

**Policy.** When a mode file does not specify a `shortcut:` field, `shortcut` defaults to the mode's `name`. Authors who want *no* slash alias write `shortcut: false` (the canonical opt-out; see §5).

**Mechanism.** A single, local change in `parse_mode_file()`. `get_shortcuts()` remains almost unchanged — its truthy gate already handles the opt-out value correctly; we add only a collision-log at the drop point.

### 4.1 Change in `parse_mode_file` (hooks-mode `__init__.py`, near L95–97)

Semantics, precisely:

1. If key `shortcut` is **absent** from `mode_config` → default to the resolved `name`.
2. If key `shortcut` is **present** and is a YAML **boolean-truthy** value (`true`/`yes`/`on` → Python `True`) → this is almost certainly an author error ("I meant to type my shortcut string but used a YAML-truthy keyword"). Log a WARNING and treat as absent (fall through to default-from-name). This guard must run **before** any `str()` coercion or validation. See M2 (Gate 1).
3. If key `shortcut` is **present** and truthy (non-empty string) → use it as-is (after `str().strip()` and lowercase normalization per MINOR-2).
4. If key `shortcut` is **present and falsy** (`false`, `null`, `""`, `0`) → explicit opt-out; `shortcut = None`.
5. After resolving, **lowercase-normalize** (MINOR-2) and then **validate** against the allowed-character regex (§7.3). If invalid, log a WARNING and set `shortcut = None`. The mode still parses successfully and remains activatable via `/mode <name>`.

Pseudocode (final implementation is the plan's concern; this is the spec):

```python
# Resolve name first (already done at L95)
resolved_name = mode_config.get("name", file_path.stem)

# Resolve shortcut with default-to-name semantics
if "shortcut" in mode_config:
    raw = mode_config["shortcut"]

    # Opt-out: explicit falsy values. `shortcut: false` is canonical; null/""/0 tolerated.
    if raw is False or raw is None or raw == "" or raw == 0:
        raw_resolved = None

    # M2 guard (Gate 1): PyYAML parses `yes`/`true`/`on` (and capitalizations) as Python True.
    # Author intent "shortcut: yes" would otherwise become str(True) == "True" and register /True.
    # Treat truthy booleans as absent + warn; fall through to default-from-name below.
    elif isinstance(raw, bool):
        logger.warning(
            "Mode file %s: shortcut value %r is a YAML boolean, not a string. "
            "To disable the shortcut, use `shortcut: false`. "
            "To use the default (the mode's name), omit the field. "
            "Treating as absent for this load.",
            file_path, raw,
        )
        raw_resolved = resolved_name  # fall through to default
    else:
        raw_resolved = str(raw).strip() or None
else:
    # Field absent → default to the mode's name.
    raw_resolved = resolved_name

# MINOR-2 (Gate 1): normalize to lowercase at parse time so slash dispatch (case-sensitive
# at main.py:361) is predictable. Authors who want mixed case must set `shortcut:` explicitly
# and accept case-sensitive dispatch (it will still be lowered here, per the tightened regex).
if raw_resolved is not None:
    raw_resolved = raw_resolved.lower()

shortcut = raw_resolved

# Validate (only if non-None). Regex is lowercase-only (see §7.3) — post-normalization
# uppercase is impossible, so a failure here means non-alnum/hyphen/underscore characters
# or a leading digit/hyphen.
if shortcut is not None and not _is_valid_shortcut(shortcut):
    logger.warning(
        "Mode file %s: shortcut %r is not a valid slash-command identifier "
        "(must match %s); no alias will be registered. "
        "The mode remains activatable via `/mode %s`.",
        file_path, shortcut, _SHORTCUT_PATTERN, resolved_name,
    )
    shortcut = None
```

### 4.2 Change in `get_shortcuts` (hooks-mode `__init__.py`, L340–356)

Minimal. The existing truthy gate already treats `None` as "do not register," so opt-out continues to work. Two refinements:

1. **Store `mode_def.name` as the dict value, not the file stem.** The `name` field is the authoritative mode identity (the same identity the CLI passes to the `mode` tool). Using the stem here would diverge from `mode_def.name` whenever an author names their file differently from their mode (e.g. file `my_mode.md`, YAML `name: my-mode`). See MINOR-1 (Gate 1).
2. **Collision log compares `mode_def.name` on both sides.** This is the correct "are these the same mode?" check. Using `stem != name` (the prior draft) falsely returned `False` when two different files both happened to have matching stems but different YAML `name` fields (or vice versa), silently swallowing the collision.

```python
if mode_def.shortcut:
    if mode_def.shortcut in shortcuts:
        existing_name = shortcuts[mode_def.shortcut]
        # MINOR-1 (Gate 1): compare on mode_def.name — the resolved winner identity —
        # not file.stem. This prevents false-negative collision suppression when
        # name != stem (e.g. file `my_mode.md` with YAML `name: my-mode`).
        if existing_name != mode_def.name:
            logger.info(
                "Shortcut collision: /%s claimed by mode %r (precedence) "
                "and again by mode %r (skipped). Set `shortcut:` explicitly "
                "on one of them to disambiguate, or `shortcut: false` to disable.",
                mode_def.shortcut, existing_name, mode_def.name,
            )
    else:
        # Store mode_def.name (not file.stem) as the resolved winner identity.
        shortcuts[mode_def.shortcut] = mode_def.name
```

### 4.3 What we do **not** change

- No change to `ModeDefinition` dataclass. `shortcut: str | None = None` remains correct — the field still holds `None` after explicit opt-out or validation failure; it only gains a non-`None` default-from-name value in the common unset case.
- No change to `get_shortcuts()` precedence ordering.
- No change to `list_modes()`.
- No change to CLI `CommandProcessor` — the consumer is untouched.
- No change to the `mode` tool (agent-initiated transitions).

## 5. Opt-out mechanism

**Decision: `shortcut: false` is the canonical opt-out form.** Other YAML-falsy values (`null`, `""`, `~`, `0`) are accepted for tolerance but not documented.

### 5.1 Option comparison

| Option | YAML parses to | Distinguishable from "omitted"? | Ergonomics | Ambiguity risk |
|---|---|---|---|---|
| `shortcut: null` | `None` | **No** — `.get("shortcut")` returns `None` in both cases unless we inspect key presence | Reads oddly; implies "this mode has a null shortcut" | Medium |
| `shortcut: false` | `False` | Yes (via key presence check; also distinguishable by type from `None`) | Reads clearly as "no, I don't want one" | **Low** |
| `shortcut: none` | String `"none"` | Yes | Misleading — `none` is not YAML null; parsed as a real string and would become the literal shortcut `/none` under naïve handling | **High** |
| `shortcut: ""` | `""` | Yes | Invisible; easy to confuse with "I forgot" | Medium |
| `shortcut: "-"` | `"-"` | Yes | Nonstandard convention; not idiomatic anywhere else in Amplifier | Medium |

### 5.2 Justification for `shortcut: false`

1. **Unambiguous YAML parse.** `false` always becomes Python `False`. No 1.1-vs-1.2 edge cases, no lowercase/capitalization traps (YAML 1.1 treats `Yes`, `No`, `On`, `Off`, `True`, `False` as booleans; all safely falsy for our check).
2. **Reads correctly.** "`shortcut: false`" is self-documenting: the author is affirmatively saying "no slash alias." `shortcut: null` would read as a declarative assertion about emptiness, which is exactly what we want to *stop* defaulting to.
3. **Does not require distinguishing "omitted" from "explicit `null`".** We still use the `"shortcut" in mode_config` key-presence check to separate "omitted" from "explicit opt-out," so all falsy values behave identically for runtime purposes. The documentation prescribes `false` for consistency.
4. **Alignment with existing Amplifier YAML conventions.** The modes bundle already uses YAML booleans elsewhere (`allow_clear: true` at `__init__.py:44`; `default_action: block`/`allow` as a string enum). `false` fits the established vocabulary.
5. **Tolerance without ambiguity.** Accepting `null`, `""`, and `0` as equivalent opt-outs costs nothing (Python falsy check) and prevents future surprises when an author tries the other obvious forms.

**Note (NITPICK-1, Gate 1): quoted `"false"` is a regular shortcut, not opt-out.** YAML distinguishes `shortcut: false` (boolean → Python `False` → opt-out) from `shortcut: "false"` (string `"false"` → a real shortcut named `false` → registers `/false`). This is YAML-correct and intentional: the opt-out signal is the boolean type, not the token. The design tolerates this rather than trying to normalize string-like-false-values, because doing so would also have to handle `"0"`, `"no"`, `"off"`, and every capitalization variant — each of which is a legitimate string shortcut someone somewhere will want. Documented in `context/modes-instructions.md` and the README (§8) alongside the opt-out syntax.

### 5.3 Python-side implementation note

The code must distinguish "key present with falsy value" from "key absent." YAML parse produces the same Python shape (`{"shortcut": None}` vs `{}` → `.get() == None`), so `.get()` alone is insufficient. Use `"shortcut" in mode_config` for key presence.

```python
if "shortcut" in mode_config:
    raw = mode_config["shortcut"]
    shortcut = str(raw).strip() if raw else None
else:
    shortcut = resolved_name
```

This is a three-line change. It is the entire disambiguation.

## 6. Backward compatibility analysis

### 6.1 Existing mode files

| Class of file | Before | After | Verdict |
|---|---|---|---|
| Has explicit `shortcut: <name>` (e.g. `careful.md`, `plan.md`, `explore.md`) | Registers `/<name>` | Registers `/<name>` (unchanged) | ✅ Identical |
| Has explicit `shortcut: <different>` | Registers `/<different>` | Registers `/<different>` (unchanged) | ✅ Identical |
| Has no `shortcut:` field (e.g. `systems-design.md` pre-fix) | Registers no alias | Registers `/<name>` | ⚠️ New alias added |
| Has `shortcut: false` (new syntax) | Was falsy → no alias (incidental) | No alias (by explicit intent) | ✅ Behavior preserved; intent now explicit |
| Has invalid `shortcut:` (e.g. with space) | Registered but unreachable | Logged warning, not registered | ⚠️ Slight behavior tightening |

### 6.2 Could anyone be relying on the *absence* of a default shortcut?

Plausible but low-probability scenarios, ranked:

1. **A user shadowed `/<name>` with a built-in command.** Impossible — built-in `COMMANDS` are checked first at `main.py:361`. The change cannot shadow any built-in. **Risk: none.**
2. **A user built a third-party shortcut-handler that intercepted `/<name>` before dispatch.** No such extension point exists in the current CLI path. **Risk: none.**
3. **Two third-party bundles both include a mode named the same thing (e.g. both have `review.md`), neither setting `shortcut:`.** Before: neither registered a shortcut; `/review` fell through to `unknown_command`. After: the first-wins mode claims `/review`; the second is silently skipped. **Risk: low, and the new collision-log (§4.2) provides diagnostic signal.** Authors who want to avoid this can opt-out with `shortcut: false` or choose a unique name.
4. **A mode author *deliberately* omitted `shortcut:` to hide the alias.** No guidance encourages this; no documentation advertises it. If it exists in the wild, the opt-out path (`shortcut: false`) is the migration. **Risk: negligible.**

### 6.3 Third-party bundles

Third-party bundles that ship mode files *without* `shortcut:` gain `/<name>` aliases automatically. This is the intended outcome — those authors almost certainly *wanted* aliases and didn't realize the field was required. If an author genuinely wants no alias, they edit one line.

## 7. Edge cases & collision handling

### 7.1 Name collisions across bundles

**Scenario.** Bundle A ships `modes/review.md` (no shortcut). Bundle B ships `modes/review.md` (no shortcut). Both claim `/review`.

- **Before this change:** Both registered no shortcut; `/review` was an unknown command. No warning.
- **After:** First-wins by search-path precedence; second is logged at INFO level (§4.2). The losing mode is still activatable via `/mode review`.

**Why this is acceptable.** The current `list_modes()` already has the same first-wins behavior at L331 (`if name not in modes:`) keyed on filename stem. Mode **files** with the same name already collide silently today. Shortcut collisions are no worse; the new collision log is an improvement.

### 7.2 Name collisions with built-in CLI commands

The dispatch order in `main.py:273, 361` checks `COMMANDS` before `MODE_SHORTCUTS`. A mode named `help`, `mode`, `modes`, `exit`, etc., would default to `/help` etc., but the built-in always wins. The mode remains activatable via `/mode help`. No change needed, but the collision log in `get_shortcuts()` does **not** detect this case (CLI COMMANDS are a separate dict). Acceptable: the consequence is invisible — user types `/help` and gets help, as expected. A future enhancement could expose `COMMANDS` to the bundle for preemptive warning, but that couples bundle and CLI and is out of scope.

### 7.3 Invalid shortcut characters and case normalization

**Problem.** `name` and `shortcut` are freeform YAML strings. A name like `my mode with spaces` or `debug/test` would produce a dict key that the CLI's whitespace-split dispatch cannot route to. Currently such a shortcut sits in `MODE_SHORTCUTS` as dead weight — registered but unreachable. Additionally, the CLI's lookup at `main.py:361` is **case-sensitive**, so a shortcut of `MyMode` requires the user to type `/MyMode` exactly — a surprising UX for a keyboard surface where every other slash command is lowercase.

**Decision (two parts).**

1. **Lowercase-normalize shortcuts at parse time** (MINOR-2, Gate 1). After resolving `raw_resolved` (§4.1), apply `raw_resolved.lower()` before validation. Consequence: a mode with `name: MyMode` and no explicit `shortcut:` gets `shortcut = "mymode"`. An author who literally wants `/MyMode` (mixed case) must set `shortcut: MyMode` explicitly — and even then the lowercase normalization applies, so mixed-case shortcuts are not supported. This is the simplest, most predictable UX: slash commands are always lowercase.

2. **Validate with a tightened, lowercase-only regex** (MINOR-2, Gate 1). Because normalization runs first, the regex can assume lowercase input:

```
_SHORTCUT_PATTERN = r"^[a-z][a-z0-9_-]*$"
```

- Starts with a lowercase letter.
- Body is lowercase letters, digits, hyphen, underscore.
- No spaces, slashes, dots, colons, or unicode (for now).
- Length bound is not enforced (consistent with current behavior); authors pick reasonable lengths.

This matches every shipped mode name in the bundle and in observed third-party bundles. It is intentionally narrower than "whatever YAML can encode" because slash commands are a keyboard-typed surface. Tightening from `[A-Za-z]` to `[a-z]` is safe because the preceding `.lower()` makes uppercase input structurally impossible at the validation step.

**Action on invalid:** log WARNING, set `shortcut = None`. The mode still loads and is activatable via `/mode <name>`. We do *not* reject the mode file, because `name` might also be the invalid value and the author might be using it only with the `/mode` form — killing the whole mode for a cosmetic issue is harsher than necessary.

### 7.4 Explicit `shortcut:` differing from `name:`

Fully supported, unchanged. E.g., `name: systems-design-review`, `shortcut: sdr` would register `/sdr` → `systems-design-review`. Authors may continue to set a short alias distinct from the long name.

### 7.5 Empty or whitespace-only explicit shortcut

`shortcut: "   "` after `.strip()` becomes `""`, which is falsy → opt-out. Equivalent to `shortcut: false`. Matches the overall tolerance policy.

### 7.6 Cache interaction

`parse_mode_file` is called from both `ModeDiscovery.find()` and `ModeDiscovery.get_shortcuts()`. Results are cached in `self._cache[name]`. The cache stores `ModeDefinition`, so the resolved `shortcut` (post-default, post-validation) is cached correctly. `clear_cache()` at L358 still works as intended. No cache invalidation change needed.

## 8. Documentation changes required (checklist)

Parity is mandatory — `context/modes-instructions.md` being out of sync with `README.md` is the original proximate cause.

- [ ] **`context/modes-instructions.md`** — *non-negotiable*. Add a "Mode Configuration" subsection documenting `name`, `description`, `shortcut` (with default-from-name and opt-out), `tools.*`, and `default_action`. This is the authoritative agent-facing context; any field an LLM should know about when authoring a mode must appear here. The section must explicitly include all of: the word `shortcut`, the word `default`, the phrase `mode's name` (or equivalent), and the token `false` (for opt-out). These are the terms the regression test (§9.6) asserts are present. Also include:
  - The quoted-`"false"` caveat (NITPICK-1): `shortcut: false` is opt-out; `shortcut: "false"` is a shortcut literally named `false`.
  - The known-limitation note (MINOR-3): modes named the same as a built-in CLI command (e.g. `help`, `mode`, `modes`, `exit`, `quit`) will have their default `/<name>` alias silently overridden by the CLI's command dispatch. They remain activatable via `/mode <name>`. To get a working slash alias in that case, set `shortcut:` explicitly to a non-reserved value.
  - The third-party naming guidance (m4): bundle-shipped modes should use descriptive, unique names (e.g. `systems-design` rather than `design`, `perf-audit` rather than `perf`). First-load wins silently on collision; the second bundle's shortcut is dropped with an INFO log.
- [ ] **`README.md`**
  - Update the "Mode Configuration" table row for `shortcut`:
    - Current: `shortcut | No | Creates /shortcut alias command`
    - New: `shortcut | No (defaults to name) | Slash-command alias. Defaults to the mode's name (lowercased). Set to false to disable. Must match /^[a-z][a-z0-9_-]*$/ after lowercasing; invalid values log a warning and register no alias.`
  - Update the "Commands" table row (n2, Gate 1). Replace the current `| /plan, /explore, /careful | Shortcuts (if defined) |` row with:
    > `| /<mode-name> | Auto-generated shortcut for each mode (use `shortcut: false` to disable, or set `shortcut:` to override) |`
  - Update the "Creating Custom Modes" example — note in-line that `shortcut:` is optional and show the opt-out form in a supplementary example.
  - Add a **"Known Limitations"** callout (MINOR-3) briefer than the context-file version: "Modes named the same as built-in CLI commands (`help`, `mode`, `modes`, `exit`, `quit`) will have their default slash alias silently overridden by the CLI; set `shortcut:` explicitly to a non-reserved value."
  - Add the **quoted-`"false"` caveat** (NITPICK-1) next to the opt-out documentation.
  - In the **Third-Party Bundle Modes** section (or create one if absent), add the naming guidance (m4, verbatim from above): prefer descriptive, unique names to avoid cross-bundle collisions.
- [ ] **`bundle.md`** — update the "Creating Custom Modes" example the same way as README. Consider removing `shortcut: mymode` from the example (it's now redundant) and noting in a comment that it's optional. **Also (m5, Gate 1): replace the stale `/mode review` usage example at `bundle.md:25`** — `review` is not a shipped mode. Change to `/mode plan` (or `/mode careful`), which are actual built-ins.
- [ ] **`modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` docstring (m3, Gate 1)** — update `parse_mode_file`'s docstring at L47–65. The current docstring shows `shortcut: plan` inside the YAML example as if the field is always required. Revise to: (a) note that `shortcut:` is optional and defaults to `name`, (b) show the opt-out form `shortcut: false` in a second example block, (c) remove any wording that implies the field must be set, (d) mention that shortcuts are lowercased and validated against `^[a-z][a-z0-9_-]*$`.
- [ ] **Changelog / release notes** — add an entry under the next minor version:
  > `shortcut:` now defaults to the mode's `name` when omitted. Set `shortcut: false` to disable. Shortcuts are lowercased at parse time and validated against `^[a-z][a-z0-9_-]*$`; invalid values log a warning and register no alias (the mode remains activatable via `/mode <name>`). Modes that previously lacked a slash alias due to the missing field will now gain one; to restore the prior behavior, add an explicit opt-out. (Fixes silent failure mode where `/<mode-name>` returned `"Unknown command"`.)
  >
  > **Known limitation (MINOR-3):** Modes whose `name` matches a built-in CLI command (`help`, `mode`, `modes`, `exit`, `quit`, etc.) will register a default shortcut that is silently overridden by the CLI's command dispatch. These modes remain activatable via `/mode <name>`. To give such a mode a working slash alias, set `shortcut:` explicitly to a non-reserved value.
  >
  > **Note:** `shortcut: false` (YAML boolean) is opt-out. `shortcut: "false"` (quoted string) is a regular shortcut named `false` and will register `/false`. Use the unquoted boolean form to disable.
- [ ] **Ensure the three shipped modes (`careful.md`, `plan.md`, `explore.md`) continue to set `shortcut:` explicitly.** They could be simplified by removing the now-redundant field, but keeping them explicit serves as in-repo documentation by example. **Decision: leave them as-is; they are the canonical reference.**
- [ ] **Add a one-line comment in the example frontmatter** (in both `README.md` and `bundle.md` examples) pointing the reader to the default semantics. E.g., `# shortcut: mymode   # Optional; defaults to `name`. Use `shortcut: false` to disable.`

## 9. Test strategy

### 9.1 Unit tests — `parse_mode_file`

Cover the parsed-shortcut states exhaustively:

| # | Input frontmatter | Expected `mode_def.shortcut` | Warning? |
|---|---|---|---|
| 1 | `shortcut: plan` | `"plan"` | No |
| 2 | `shortcut: p` (different from name) | `"p"` | No |
| 3 | key omitted, `name: explore` | `"explore"` (default-from-name) | No |
| 4 | `shortcut: false` | `None` (explicit opt-out) | No |
| 5 | `shortcut: null` | `None` (tolerated opt-out) | No |
| 6 | `shortcut: ""` | `None` (tolerated opt-out) | No |
| 7 | `shortcut: "  my mode  "` → invalid after strip | `None` | Yes (invalid chars) |
| 8 | `shortcut: "my/mode"` | `None` | Yes (invalid chars) |
| 9 | key omitted, `name: "my mode"` (name itself invalid) | `None`; mode still parses | Yes (invalid chars) |
| 10 | key omitted, `name` also omitted → `name` defaults to file stem `foo` | `"foo"` | No |
| **11** | `shortcut: "false"` (quoted string) — NITPICK-1, Gate 1 | `"false"` (a real shortcut named `false`) | No |
| **12a** | `shortcut: yes` (YAML-truthy boolean → Python `True`) — M2, Gate 1 | default-from-name (falls through per §4.1 step 2) | **Yes (boolean-not-string warning)** |
| **12b** | `shortcut: true` — M2, Gate 1 | default-from-name | Yes (boolean-not-string warning) |
| **12c** | `shortcut: on` — M2, Gate 1 | default-from-name | Yes (boolean-not-string warning) |
| **13** | `name: MyMode`, no explicit shortcut — MINOR-2, Gate 1 | `"mymode"` (lowercased at parse time) | No |
| **14** | `shortcut: MyMode` — MINOR-2, Gate 1 | `"mymode"` (lowercased at parse time) | No |
| **15** | `shortcut: 0mode` (leading digit; fails tightened regex) — MINOR-2, Gate 1 | `None` | Yes (invalid chars) |

Assertion style: unit tests instantiate `parse_mode_file` against temp-file fixtures and check both the returned `ModeDefinition` and (via `caplog` or equivalent) the log output for cases 7–9, 12a–c, and 15.

**Note on case 11 vs case 4.** These are YAML-semantically distinct: `shortcut: false` (unquoted, boolean) is opt-out; `shortcut: "false"` (quoted, string) is a shortcut named `false`. The test matrix covers both to prevent accidental regression of the YAML-boolean-vs-string distinction.

### 9.2 Unit tests — `ModeDiscovery.get_shortcuts`

| # | Scenario | Expected `shortcuts` dict |
|---|---|---|
| 1 | Single mode, no field (**key** = `mode_def.shortcut` = registered alias; **value** = `mode_def.name` = winning mode identity — NITPICK-3, Gate 1) | `{"<name>": "<name>"}` (keys and values agree in the common case) |
| 2 | Single mode, explicit field | `{"<explicit>": "<name>"}` |
| 3 | Single mode, opt-out | `{}` |
| 4 | Two modes, same default shortcut, across two search paths | First-wins by path precedence; INFO log emitted for the loser |
| 5 | Two modes with explicit but conflicting shortcuts | First-wins; INFO log |
| 6 | Mode with invalid shortcut | Excluded; no entry in dict (validation happened in `parse_mode_file`) |
| **7** | File `my_mode.md` with YAML `name: my-mode`, no explicit shortcut (MINOR-1, Gate 1 — covers stem≠name divergence) | `{"my-mode": "my-mode"}`. **Critically:** the dict value is `"my-mode"` (the YAML `name`), not `"my_mode"` (the stem). |
| **8** | Two files `my_mode.md` and `mymode-v2.md`, both with YAML `name: my-mode`, no explicit shortcut (MINOR-1, Gate 1) | `{"my-mode": "my-mode"}` (first-wins). The guard `existing_name != mode_def.name` compares `"my-mode" != "my-mode"` → False → collision is **NOT** logged (both files claim the same resolved identity; silent first-wins applies per §4.2 code — this is the common project-overrides-bundle case). Variant (variant 2): if the second file's YAML `name` differs (e.g. `name: my-other-mode`), the key `"my-mode"` still collides — existing_name `"my-mode"` != new name `"my-other-mode"` → collision logged. |

**Key/value semantics (NITPICK-3).** In the `shortcuts` dict:
- **Key** is `mode_def.shortcut` — the registered slash-command alias. What the CLI routes on.
- **Value** is `mode_def.name` — the mode's identity. What the CLI passes to the mode-activation path.
- In the common case these are identical strings (default-from-name). They diverge when the author sets an explicit `shortcut:` or when file stem differs from YAML `name`. Storing `mode_def.name` (not `file.stem`) is what makes the collision guard in §4.2 compare like-for-like.

### 9.3 Integration test — end-to-end mode discovery

Construct a fake bundle layout in a `tmp_path`:

```
fake-bundle/
├── modes/
│   ├── alpha.md        # shortcut omitted, name: alpha
│   ├── beta.md         # shortcut: false
│   └── gamma.md        # shortcut: g
```

Invoke `ModeDiscovery(search_paths=[(tmp_path / "fake-bundle" / "modes", "test")]).get_shortcuts()` and assert:
- `shortcuts == {"alpha": "alpha", "g": "gamma"}`
- No `beta` key.

### 9.4 DTU (digital twin) end-to-end

This validates the *entire* path, including the CLI `CommandProcessor` registration at startup, which is out of reach from pytest against the bundle alone.

**Setup:** a Digital Twin Universe with Amplifier installed, composed with `amplifier-bundle-modes` (under test) and a minimal probe bundle containing one mode file with no `shortcut:` field:

```yaml
---
mode:
  name: probe
  description: DTU probe mode
  tools:
    safe: [read_file]
  default_action: block
---
PROBE MODE active.
```

**Assertions:**
1. Fresh Amplifier session → `/modes` lists `probe`.
2. `/probe` activates the mode (prompt shows `[probe]>`, not `"Unknown command"`).
3. `/mode probe` still works (unchanged regression check).
4. Add a second probe bundle with `shortcut: false` → `/probe2` returns `"Unknown command"`; `/mode probe2` works.

The DTU run is the authoritative sign-off gate — if it passes, the original reported symptom is resolved end-to-end.

### 9.5 What we explicitly do not test

- CLI command parsing edge cases (unicode, quoted commands) — out of scope for the bundle; owned by CLI.
- Interaction with the `mode` tool (agent-initiated transitions) — unchanged by this design; existing tests suffice.

### 9.6 Regression test — documentation parity for `context/modes-instructions.md` (M1, Gate 1)

This test exists specifically to prevent recurrence of the original proximate cause: `context/modes-instructions.md` omitting `shortcut:` entirely, causing authoring LLMs to generate shortcut-less mode files. A naïve grep-for-`shortcut:` check (the Rev 0 draft) is insufficient — it would pass on a file that merely mentions the word in a deprecation comment, or that describes the wrong semantics. The strengthened assertion checks that multiple terms required for correct documentation all appear.

```python
def test_modes_instructions_documents_shortcut_semantics():
    """The agent-facing context file must document the shortcut default + opt-out.

    This test exists because the original bug (papayne's systems-design bundle) was
    caused by `context/modes-instructions.md` omitting `shortcut:` entirely. A grep-for-
    keyword check is insufficient — it would pass on a file saying "the shortcut field
    was deprecated". This test verifies multiple terms appear, signaling the file
    documents the correct semantics.
    """
    content = (bundle_root / "context" / "modes-instructions.md").read_text().lower()
    required_terms = ["shortcut", "default", "name", "false"]
    missing = [t for t in required_terms if t not in content]
    assert not missing, (
        f"context/modes-instructions.md is missing required documentation terms: {missing}. "
        f"The file must document: the shortcut field, that it defaults to the mode's name, "
        f"and that `shortcut: false` disables it."
    )
```

This replaces the grep approach in the Rev 0 draft. The four terms (`shortcut`, `default`, `name`, `false`) are the minimum vocabulary a correct documentation section must contain. If a future doc refactor renames these (e.g. uses "alias" instead of "shortcut"), the test will fail — and that's the correct behavior: intentional doc changes should touch this test deliberately, not silently.

A parallel, narrower test should assert the same for `README.md`'s Mode Configuration table row and its Commands table row — the README is user-facing and must also describe default-from-name + opt-out. The README test can be structurally identical: same four required terms, same `.lower()` + `in` check.

## 10. Alternatives considered

### 10.1 Docs-only fix (add `shortcut:` to `modes-instructions.md`, leave behavior unchanged)

**What it would do.** Teach authoring LLMs that the field exists, relying on them to include it in every new mode.

**Why it loses.**
- Requires every author (human or LLM) to consult and remember the doc every time. The existing README already documents the field — papayne's bundle was still written without it because the *agent-facing* context omitted it. A docs-only fix just moves the gap from one file to another; it does nothing for mode files generated before the doc was updated, and nothing for authors working from cached context or forks.
- Does not change the failure mode: silent omission still produces silently-broken modes.
- The field is effectively required for usable UX. Documenting it as "optional, but you really should set it" is an anti-pattern the code should fix directly.

**Verdict:** retained as a *complementary* step (§8 still updates `modes-instructions.md`), but insufficient as the sole fix.

### 10.2 Require `shortcut:` — reject mode files missing the field

**What it would do.** `parse_mode_file()` returns `None` and logs an error if `shortcut:` is absent, preventing the mode from loading.

**Why it loses.**
- Breaks every existing third-party mode file that relies on the undocumented default. The systems-design bundle and any others in the wild would stop loading entirely until patched.
- Forces authors who genuinely want no slash alias to add ceremony (the opt-out syntax) just to get today's "do nothing" behavior.
- Fights the "be liberal in what you accept" principle. The default-from-name design gets 100% of the usability benefit without the breakage.

### 10.3 Register a shortcut at registration time instead of parse time

**What it would do.** Keep `parse_mode_file()` unchanged (`shortcut` stays `None` when omitted). In `get_shortcuts()`, when `shortcut is None`, fall back to `mode_def.name`.

**Why it loses (lead argument, NITPICK-4 Gate 1).** `ModeDefinition.shortcut` should be **the single resolved representation** of the slash-command alias. After parse, `None` means "no shortcut, no alias" — unambiguous, one source of truth. Any consumer (future tooling, debug inspectors, documentation generators, log formatters) sees the resolved value directly on the dataclass without having to re-implement the default-from-name rule. Splitting the default across `parse_mode_file` (produces `None`) and `get_shortcuts` (interprets `None` as "use name") forces every consumer to know the rule. The dataclass field stops being self-describing and becomes a partial intent that requires downstream interpretation.

**Why it loses (secondary).**
- **Style observation.** Reading `ModeDefinition` in isolation, a `shortcut = None` would look like "this mode has no shortcut." With the registration-time fallback, that reading is wrong — it actually means "this mode defaults to its name." Misleading dataclasses cost reader-time forever.
- **Splits default across two files.** Maintainers have to follow the field's meaning across `parse_mode_file` and `get_shortcuts` to understand what a given `None` signifies. Parse-time resolution collapses that to one place.
- **Doesn't meaningfully simplify** — the three-line key-presence check lives somewhere either way. We pay the same cost, just with worse encapsulation.

**Verdict:** technically works, but §4.1 placement is cleaner. Parse-time is where defaults belong.

### 10.4 `shortcut: null` / `shortcut: none` / `shortcut: "-"` as opt-out

Rejected in §5.1–5.2. Summary: `false` is the unambiguous, readable, YAML-idiomatic choice.

### 10.5 Auto-sanitize invalid shortcut characters

**What it would do.** `"my mode"` → `"my-mode"`; `"debug/test"` → `"debug-test"`.

**Why it loses.**
- Silent magic. Authors expect `/my mode` (doesn't work anyway) or expect to see a warning — they do not expect a different shortcut to quietly appear.
- Ambiguous: do we lowercase? Collapse multiple hyphens? Strip leading digits? Every rule adds surface area.
- The real fix is to tell the author (§7.3). Warn, skip, keep `/mode <name>` working. Silent is worse than surfaced.

## 11. Risks & mitigations

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | A third-party mode `foo.md` without `shortcut:` now claims `/foo`, colliding with an unrelated non-bundle concept in the user's mental model | Low | Opt-out (`shortcut: false`) is one line. Collision across modes is logged. Collision with built-in commands is impossible (COMMANDS wins). |
| R2 | The author of a pre-existing third-party bundle intentionally omitted `shortcut:` and this change adds unwanted aliases | Low | Changelog flags the behavior change clearly. Opt-out is trivial. No observed evidence this pattern exists in the wild. |
| R3 | Regex validation is too strict and rejects a valid name in an existing bundle | Medium | Regex matches every shipped mode and observed third-party mode. Validation failure *doesn't* kill the mode — only the alias. Activation via `/mode <name>` remains available. If a real-world mode name fails, we loosen the regex in a patch release. |
| R4 | Silent first-wins collision obscures a real bug (two bundles genuinely fighting for the same alias) | Medium | New INFO log in `get_shortcuts()` surfaces the collision. Escalating to WARNING is considered but rejected — many legitimate cases (project mode overrides bundle mode) look identical and shouldn't produce warnings. INFO is the right level. |
| R5 | Authors confused by the three-way distinction: explicit string / omitted / explicit-false | Low | Documentation in `modes-instructions.md` and `README.md` spells it out with examples. The opt-out form is one canonical keyword (`false`). |
| R6 | A rarely-used fifth search path type surfaces an edge case parse_mode_file hasn't seen | Low | All search paths funnel through `parse_mode_file`. No special casing per source. Unit tests cover parsing itself, not discovery plumbing. |
| R7 | Documentation parity drifts again in the future (the original root cause) | Medium | Regression test in §9.6 (M1, Gate 1): asserts `context/modes-instructions.md` contains **all** of the terms `shortcut`, `default`, `name`, `false` (case-insensitive). A parallel test asserts the same for `README.md`. Strengthened from the Rev 0 grep-for-`shortcut:` approach, which a deprecation comment could satisfy — the multi-term check requires the file to actually describe the semantics (field + default + identity + opt-out token) rather than merely name the field. |

## 12. Rollback plan

### 12.1 For authors who dislike the new default

One-line fix per mode file: add `shortcut: false`. No code change needed. Documented in §8 changelog entry and in the opt-out examples. This is the primary rollback — it restores the pre-change behavior per-mode without reverting the bundle.

### 12.2 For bundle consumers who want to pin the old behavior globally

Pin the bundle dependency to the last pre-change version (e.g., in `bundle.md`):

```yaml
hooks:
  - module: hooks-mode
    source: git+https://github.com/microsoft/amplifier-bundle-modes@<pre-change-tag>#subdirectory=modules/hooks-mode
```

The change is localized to `hooks-mode`; pinning it does not forfeit unrelated bundle features.

### 12.3 For the bundle maintainer

Revert the PR that introduced this change. Because the change is isolated to:
- ~15 lines in `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py` (parse + get_shortcuts)
- Documentation in three files (`README.md`, `bundle.md`, `context/modes-instructions.md`)
- Unit and integration tests

…a revert is mechanical and complete. No migrations, no schema changes, no persisted state to unwind. Caches (`ModeDiscovery._cache`) are per-session and rebuilt on startup; no stale data survives across the rollback.

### 12.4 Rollback signal

If post-release we observe any of:
- Widespread collision-log chatter indicating many third-party modes fighting for the same default shortcut (suggests `/mode` activation would have been the better UX default), or
- Validation rejections of real-world mode names (suggests the regex is wrong), or
- User reports that unexpected `/<name>` aliases are being added and interfering with their workflow,

…we ship a patch release that either (a) gates the default behind a bundle-config flag (`default_shortcut_to_name: true/false`) defaulting to `false` for compatibility, or (b) loosens the validation regex, or (c) reverts entirely. Option (a) is the most invasive and least preferred; we'd try (b) first.

---

## Appendix A: Cited file:line references

All claims about current behavior are grounded at these locations:

- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:36` — `ModeDefinition.shortcut: str | None = None`
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:47–106` — `parse_mode_file`; key fields at L95 (`name`), L97 (`shortcut`)
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:321–338` — `list_modes` (no `shortcut` dependency)
- `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py:340–356` — `get_shortcuts`; truthy gate at L353
- `modes/careful.md:5`, `modes/plan.md:5`, `modes/explore.md:5` — reference `shortcut:` in shipped modes
- `README.md:126–137` — Mode Configuration table (docs to update)
- `bundle.md:39–51` — example frontmatter (docs to update)
- `context/modes-instructions.md:44` — current omission of `shortcut` (docs to update; non-negotiable)
- CLI `amplifier_app_cli/main.py:273` — `COMMANDS` dict (precedence; unchanged)
- CLI `amplifier_app_cli/main.py:314, 325, 327–333` — `MODE_SHORTCUTS` registration
- CLI `amplifier_app_cli/main.py:361` — dispatch check
- CLI `amplifier_app_cli/main.py:374` — `"unknown_command"` fall-through (the observed symptom)

## Appendix B: Philosophy alignment

- **Mechanism vs policy.** The bundle's `hooks-mode` remains the mechanism (parse, discover, register). This change introduces a new *policy*: "an omitted shortcut defaults to the mode's name." The policy is expressed at the bundle boundary, not in the kernel. Kernel code is untouched.
- **Occam's Razor.** The implementation is three lines of semantic change in `parse_mode_file`, one collision log in `get_shortcuts`, one regex, and documentation parity. Nothing in the dataclass, discovery traversal, caching, or CLI changes.
- **Liberal in what you accept, conservative in what you emit.** The design accepts `false`, `null`, `""` all as equivalent opt-outs, but documents only `false`. It tolerates extra whitespace via `strip()`. It rejects invalid shortcuts with a warning rather than crashing. It logs collisions at INFO, not WARNING, because the common case (project overrides bundle) shouldn't be noisy.
- **Regenerate over patch.** The policy shift is expressed in the one place policy lives (`parse_mode_file`). A future maintainer who wants different semantics regenerates that function; nothing else needs to move.
