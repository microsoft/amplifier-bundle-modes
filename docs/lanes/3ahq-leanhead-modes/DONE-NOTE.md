# DONE-NOTE — lane `3ahq-leanhead-modes` (`model_performance-va53`)

**Outcome: A — RESOLVED.** Every deliverable is DONE except the two CI-run URLs,
which are NOT-POSSIBLE for a stated, pre-authorised reason (this repo has no CI
at all). **Spend: $0.00 of $0.00.** No API call, no DTU, no infrastructure
created, nothing to tear down.

Repo: `microsoft/amplifier-bundle-modes` · branch `lane/3ahq-leanhead-modes` ·
merge-base `3e2a9e6b0727844d5c1fefd42742a79bf466dd27`.

---

## 1. What shipped

Two commits, three files, no file outside this repo touched.

| Commit | What |
|---|---|
| `666e37c` | `test(head)`: the guardrail + vendored v1 fixture — lands FIRST so the suite goes RED |
| `79ccd37` | `perf(context)`: applies the lean rewrite — turns it GREEN |

```
context/modes-instructions.md                            |  94 +-----
modules/hooks-mode/tests/fixtures/lean-head-v1/v1_pins.json |  24 ++
modules/hooks-mode/tests/test_lean_head_guardrail.py     | 305 +++++++++++
3 files changed, 338 insertions(+), 85 deletions(-)
```

## 2. Deliverables

| # | Deliverable | State |
|---|---|---|
| 1 | The patch applied (never force-applied with fuzz) | **DONE** — applied *cleanly*, §3 |
| 2 | Fidelity table re-verified at today's head | **DONE** — §4, 0 rules lost |
| 3 | Stock → lean char counts | **DONE** — §5 |
| 4 | Byte-for-byte pin test against the v1 text | **DONE** — §6, both artifacts |
| 5 | `mode` tool description verified and skipped | **DONE** — §7, byte-identical |
| 6 | CI: this repo has NONE — say so plainly | **DONE** — §8 |
| 6b | *(item acceptance)* red + green **CI run URLs** quoted | **NOT-POSSIBLE** — §8 |
| 7 | Draft PR, not merged | **DONE** — §9 |
| 8 | DONE-NOTE at the lane artifact root | **DONE** — this file |

## 3. The patch applied CLEANLY — no fuzz, no hand-port

Source: `microsoft/amplifier-foundation` main, artifact directory
`docs/lanes/zc6t-lean-head-ship/patches/context-files/03-amplifier-bundle-modes-modes-instructions.md.patch`
(read at foundation `a97a9c0`, from PR #372's merged lane directory).

```
$ git apply --check --verbose .../03-amplifier-bundle-modes-modes-instructions.md.patch
Checking patch context/modes-instructions.md...
$ git apply --verbose ...
Applied patch context/modes-instructions.md cleanly.
```

`git apply` matches context exactly and has no fuzz mode, so "cleanly" here means
byte-exact placement — not `patch(1)`'s "succeeded at N with fuzz 2". The
hand-port path (precedent `l4s1`) was **not needed**: the head had moved since
zc6t (`3e2a9e6`, PR #29 relocated the mode-authoring material into
`mode-schema-reference.md`), but that move is *already inside* the patch's
a-side, so the 86-line stock file the patch expects is exactly the 86-line stock
file at today's head.

Independent confirmation that placement is right, not merely accepted: the
post-apply file is **byte-identical to `v1_instructions.json` span 3's body**
(`sha256 4b55377693ed28d4…`), which is a value derived from the measurement, not
from the patch.

## 4. Fidelity — re-verified at today's head, NOT inherited

Full transcript: `evidence/fidelity-recheck.txt`.

**Mechanical sweep.** 35 backticked tokens in the stock text; **3 absent
literally**, all three pre-adjudicated on the item and re-confirmed here as
FALSE POSITIVES:

| Stock token | Lean form carrying it |
|---|---|
| `mode(operation="list")` | `mode(operation="set"\|"clear"\|"list"\|"current")` and `mode(operation="list"\|"current"\|"clear")` |
| `mode(operation="current")` | same |
| `mode(operation="clear")` | same |

Operations reachable from the lean text's own `mode(operation=…)` constructs:
`['clear', 'current', 'list', 'set']` — all four stated. Presentation changed
(four-row table → alternation); no rule dropped.

**Semantic sweep.** 25 rules / commands / pointers checked one by one — the four
commands, the context-injection marker, the `[mode]>` indicator, all four tool
policies, the `default_action` fallback, the whole infrastructure-tools bypass
(`hooks-mode`, `infrastructure_tools: ["mode", "todo"]`, `tools.safe`, §3.4, "not
a trap"), both custom-mode directories, both authoring pointers, the ephemeral-
capabilities rule and its three check surfaces.

**RULES LOST: 0. Nothing needed restoring.** zc6t's `fidelity-report.json`
recorded 4 flags across all 23 targets — 3 false positives and one genuine loss
(`edit_file`, +450 chars, a **different** repo). This repo carries none of the
genuine loss; entry `[3]` of that report is this file, and its three flags are
the false positives above.

Prose that is gone and is *not* a rule, recorded so nobody has to re-derive it:
the warn-gate rationale sentence, the "when the `mode` tool is available"
conditional framing, and the "Anti-pattern:/Correct pattern:" labels (both
behaviours survive as prose).

## 5. Char counts

| Artifact | Stock | Lean | Saved |
|---|---:|---:|---:|
| `context/modes-instructions.md` | **4,870** | **2,403** | **2,467** (50.7%) |
| `mode` tool description | **198** | **198** | **0** (already v1) |

Chars, not bytes and not tokens — same unit as the published head census. (Bytes:
4,887 → 2,415; the file contains multibyte `·`, `—`, `→`, `§`.) These match
zc6t's `fidelity-report.json` entry `[3]` exactly (4870/2403/2467), recomputed
here rather than copied.

The wire body is 2,402 chars; the file is 2,403 because the `<context_file>`
wrapper consumes the file's trailing newline when rendering. The fixture and the
pin both record this explicitly so the off-by-one can never be mistaken for
drift.

## 6. The pin test

`modules/hooks-mode/tests/test_lean_head_guardrail.py` — 45 tests, pure Python,
filesystem-only, no network and no API key. Vendored verbatim v1 text in
`modules/hooks-mode/tests/fixtures/lean-head-v1/v1_pins.json`, carrying its own
sha256 and char counts plus a self-consistency test so a hand-edit of the
fixture fails loudly instead of silently moving the pin.

It asserts, per artifact:

1. **byte pin** — `context/modes-instructions.md` == vendored v1 text;
2. **byte pin** — `ModeTool.description` (AST-extracted from source, no import)
   == vendored v1 text;
3. **char budgets** — 2,403 and 198, pinned **per artifact, never to a
   whole-head absolute** (zc6t measured a real head at 320,410 chars against the
   parent item's 48,249 figure — a whole-head number in a per-repo test would be
   pinning a fiction);
4. **the saving is arithmetic in the repo** — 4,870 − 2,403 == 2,467;
5. **fidelity** — 24 exact code literals + 9 prose phrases + all four
   `mode(operation=…)` values + each of the four policies *with its behaviour
   word* + the infrastructure-tools bypass including "not a trap".

**Fail-before / pass-after, run locally (`evidence/guardrail-{RED-stock,GREEN-lean}.txt`):**

| Against | Result |
|---|---|
| pre-change stock text (`666e37c`) | **2 failed, 43 passed** — `test_modes_instructions_byte_pinned_to_v1`, `test_context_file_char_budget` |
| post-change lean text (`79ccd37`) | **45 passed** |

Exactly as the acceptance requires: RED on the context file, and **every
`mode`-description assertion PASSES in both arms** — because that text needed no
change.

## 7. `mode` tool description: verified, byte-identical, left untouched

Transcript: `evidence/mode-tool-description-verify.txt`.

```
shipped chars: 198  sha256 02b7364bddf04e4c4c20dd42a0cc993e6faff35ae4b17ff4b153c0686d28c3bb
v1      chars: 198  sha256 02b7364bddf04e4c4c20dd42a0cc993e6faff35ae4b17ff4b153c0686d28c3bb
BYTE-IDENTICAL: True
```

Shipped source `modules/tool-mode/amplifier_module_tool_mode/__init__.py` →
`ModeTool.description`, compared against `v1_tools.json['mode']` in
`openai-evals-team-ci .amplifier/evaluation/probes/bji-lean-head/`. Corroborates
zc6t finding **F3** (`"status": "identical-skip"`, entry `[21]`).

**No edit was made and none was warranted.** Eleven tool descriptions actually
change across the ecosystem, not thirteen; no file was edited to make a count
match. The only change this artifact receives is being **pinned**, so it cannot
drift away from v1 later.

## 8. CI — this repo has none

`.github/workflows` **does not exist** in `microsoft/amplifier-bundle-modes`.
There is no CI run to be red or green, and no run URL to quote. This is stated
plainly rather than implied away: **no green CI run is being claimed.** This repo
is one of the 18 in the `j1e6-ci-*` lane, which is queued *behind* this one on
purpose — the pin test is the thing worth guarding, and CI is what will make it
execute on every future PR. Wiring CI here would have handed that lane a green
run over a suite that did not yet contain the pin, and would have collided with
its own scope.

**Substitute evidence, of the same shape:** the fail-before/pass-after
transcripts in §6, taken commit-by-commit, plus the full-suite baseline below.

**Local suite — the honest number.** The repo's suite is **not green at the
merge-base**, for reasons that predate this lane:

| | hooks-mode | tool-mode |
|---|---|---|
| baseline @ `3e2a9e6` | 1 failed, **251** passed | 1 failed, **52** passed |
| post-change @ `79ccd37` | 1 failed, **296** passed | 1 failed, **52** passed |

Same two failures, before and after. **Zero new failures; +45 passing.** The two
pre-existing failures (`evidence/suite-BASELINE-merge-base.txt`, produced from a
detached worktree at the merge-base):

1. `hooks-mode tests/test_token_cost_when_inactive.py` — `handle_provider_request`
   returns `inject_context` where the test requires `continue` when no mode is
   active.
2. `tool-mode tests/test_tool_mode.py::TestClearedEvent::test_clear_active_mode_emits_mode_cleared`
   — the `mode:cleared` payload carries an extra `name` key.

Both are product/test-contract mismatches in code this lane does not own and does
not touch. **Decision recorded (no human was waited on): the PR stays a DRAFT.**
The instruction is "mark ready when the local suite is green", and it is not
green — so claiming ready would be exactly the kind of implied-green this note
exists to avoid. The manager can mark it ready knowing the delta is 0 new
failures, or route the two pre-existing failures to their own item.

**Reproducing the suite** (neither module's tests run from a bare checkout — they
need each other on the path, and one hooks-mode test imports `amplifier_foundation`):

```bash
uv venv /tmp/v && VIRTUAL_ENV=/tmp/v uv pip install pytest pytest-asyncio pyyaml \
  "git+https://github.com/microsoft/amplifier-foundation@main"
R=$PWD
for m in hooks-mode tool-mode; do (cd modules/$m && \
  PYTHONPATH=$R/modules/hooks-mode:$R/modules/tool-mode /tmp/v/bin/python -m pytest -q); done
```

Running `pytest modules` from the repo root collides on the duplicate `tests`
package name and collects nothing — worth knowing before the CI lane writes a
workflow for it.

## 9. Spend

**$0.00 spent against a $0.00 authority** (`0 runs × 0 arms × $0 / 1.00 = $0.00`,
slack $0.00). No API measurement was authorised and none was made. The
arithmetic closes trivially because this lane buys nothing: applying a
pre-measured patch and running a local suite. No residue, no unspendable
remainder, no infrastructure registered or claimed, nothing to tear down.

Cited, never re-bought:

- **`g7h3`** — 98 end-to-end `claude-opus-5` / S7-17 runs (49/arm, $428.10):
  Δ$/task **−13.57%, 95% CI [−22.27%, −4.86%]** (VALID-only primary, n 11/8);
  ALL-runs **−16.42%, CI [−23.29%, −9.56%]**; block-paired **−14.44%, CI
  [−26.83%, −2.06%]**. All three exclude zero — first time in the program.
- **`5zp`** — quality co-primary, one-sided 95% LB **−7.15 pp** against the
  frozen **−10 pp** non-inferiority margin: CLEARS.

**Scope of that claim, stated because it is easy to over-read:** it is measured
on **Anthropic / `claude-opus-5`**, where the direct term is ~4.2× larger.
**`terra` remains HOLD-because-underpowered (MDE 21.7%), not a measured wash**,
and `B` has the *opposite sign* on the two providers — do not extrapolate across
one. Per §5 rule 9 (Anthropic is the hard constraint), no new guardrail run was
bought: the Anthropic evidence is `g7h3`'s own 98 runs on the daily driver.

## 10. Findings

**F1 — DEFECT IN THIS LANE'S `GOAL.md`, not in the work.** `GOAL.md`'s Task
section says *"this lane owns ONLY the `amplifier-module-tool-filesystem` slice:
`read_file`, `write_file`, `edit_file`, `grep`, `glob`"*, tells the lane to fetch
from `patches/tool-descriptions/`, and asserts *"THIS REPO CARRIES THE ONE REAL
WEAKENING zc6t FOUND — `edit_file`"*. **None of that is this repo.** The
checkout is `amplifier-bundle-modes`; work item `model_performance-va53` targets
`patches/context-files/03-…` plus verify-and-skip on `mode`; the `edit_file`
weakening belongs to the filesystem repo. This is a sibling lane's goal text
pasted into this one — the same class of error as the parent's 14-repos /
one-checkout mismatch that produced zc6t's finding F1.

*Resolution taken:* `GOAL.md` itself says **"THE WORK ITEM … IS THE SPEC"**, so
the work item was followed and the goal's slice sentence was disregarded. Every
option the item offers has a target inside this repo, so no fourth outcome branch
was needed. Two paragraphs of `GOAL.md` are, however, actively misleading to any
later reader and should be corrected at the source.

**F2 — the head has moved since zc6t, and the patch still fit.** `3e2a9e6`
(PR #29) restructured this very file after the patch was written. The patch
applied byte-exactly anyway, because #29's change is inside the region the patch
replaces wholesale. Worth recording: "the head moved" does **not** imply "port by
hand" — check first, and confirm placement against a value derived from the
measurement (here, the v1 span sha256), not against the patch's own success.

**F3 — `__pycache__/*.pyc` files are tracked in this repo.** Running the suite
dirties the working tree with binary churn, and `.gitignore` contains only
`dist/`. Nothing was committed from it here (staging was explicit, per-path), but
the CI lane will trip over it. Not this lane's slice; filed as an observation.

**F4 — the pin's unit trap, documented so it cannot bite twice.** The v1 wire
body is 2,402 chars and the file is 2,403; bytes are 2,415. A pin written against
the wrong one of those three numbers would look authoritative and be wrong. The
fixture stores the exact text and its own sha256, and the test compares text,
never a length alone.

---

## Evidence

| File | What it is |
|---|---|
| `evidence/fidelity-recheck.txt` | the full 35-token + 25-rule sweep, run at today's head |
| `evidence/mode-tool-description-verify.txt` | the `mode` byte-identity proof |
| `evidence/guardrail-RED-stock.txt` | guardrail vs pre-change text — 2 failed, 43 passed |
| `evidence/guardrail-GREEN-lean.txt` | guardrail vs post-change text — 45 passed |
| `evidence/suite-BASELINE-merge-base.txt` | full suite at `3e2a9e6`, before this lane |
| `evidence/suite-POST-change.txt` | full suite at `79ccd37` |
