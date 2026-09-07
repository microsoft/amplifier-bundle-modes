# DONE-NOTE — lane `j1e6-ci-modes` (`model_performance-j1e6`)

**Outcome: A — RESOLVED.** Every deliverable is **DONE**. Nothing was recorded
NOT-POSSIBLE, so outcome branch B does not apply; nothing was unreachable, so
branch C does not apply.

**Spend: $0.00 of the $0 authority.** CI minutes only — 2 gating runs. No API
call, no DTU, no container, nothing registered in the infra ledger, nothing to
tear down.

| | |
|---|---|
| Repo | `microsoft/amplifier-bundle-modes` |
| Branch | `lane/j1e6-ci-modes` |
| Merge-base / main HEAD at start | `d7f5f2e4ea50203c635152dccdd919348f723742` |
| PR | https://github.com/microsoft/amplifier-bundle-modes/pull/32 (**draft → ready; NOT merged**) |
| RED run | https://github.com/microsoft/amplifier-bundle-modes/actions/runs/34156524100 |
| GREEN run | https://github.com/microsoft/amplifier-bundle-modes/actions/runs/34156650604 |
| Scratch PR | #31 — **CLOSED**, branch `ci/red-proof-j1e6` **DELETED** (verified by remote read) |

---

## 1. Deliverables

| # | Deliverable | State |
|---|---|---|
| 1 | `.github/workflows/ci.yml` running the real suite, ruff pinned, `push:main` + `pull_request`, no path filters / error-tolerating directives / exit-code discards | **DONE** — §2 |
| 2 | BOTH run URLs quoted in the PR body; the RED run's job log shows the suite executing with a genuine **test** failure | **DONE** — §3 |
| 3 | Scratch PR closed and its branch deleted — **verified, not assumed** | **DONE** — §3.3 |
| 4 | A statement of what the suite actually covers (test count, or "import smoke only") | **DONE** — §2.2, **350 real tests, not a smoke** |
| 5 | Clean main red → STOP, report, fix as **separate named commits**, never by weakening the workflow | **DONE** — §4, five findings, four commits |
| 6 | DRAFT PR, marked ready when green, **NOT merged** | **DONE** — §5 |
| 7 | DONE-NOTE at the lane artifact root (never the repo root) | **DONE** — this file |

---

## 2. What shipped

Five commits. No file outside this repo touched; no file outside the paths this
lane owns.

| Commit | What |
|---|---|
| `7f605f3` | `test(hooks-mode)`: assert the shipped mode-status contract in the inactive-session test |
| `027cfc5` | `test(tool-mode)`: assert the dual-key `mode:cleared` payload the emitter actually sends |
| `95cface` | `docs(events)`: document the dual-key payloads tool-mode actually emits |
| `60ce7ea` | `fix(tests)`: clear the three genuine ruff findings on main |
| `2ebb51c` | `ci`: add a red-then-green-proven workflow |

### 2.1 The gate

Three job definitions → **six checks** on `push:main` and `pull_request:main`:

| Check | What | Green result |
|---|---|---|
| Lint | ruff **PINNED 0.16.6**, `--isolated --select E4,E7,E9,F` | `All checks passed!` |
| Tests — hooks-mode (py3.11) | the module's real suite | `297 passed in 1.02s` |
| Tests — hooks-mode (py3.13) | " | `297 passed in 0.90s` |
| Tests — tool-mode (py3.11) | " | `53 passed in 0.33s` |
| Tests — tool-mode (py3.13) | " | `53 passed in 0.27s` |
| Bundle structure (YAML) | `bundle.md` frontmatter + `behaviors/*.yaml` | `2 YAML document(s) parsed. Bundle structure OK.` |

Verified by `grep` on the committed file: it contains no path filter, no
error-tolerating job/step directive, and no exit-code-discarding shell
fallback — **not even in prose**, so a reviewer grepping for those tokens gets
a clean result.

### 2.2 What the suite actually covers — 350 tests, NOT an import smoke

`modules/hooks-mode` 297 + `modules/tool-mode` 53 = **350**. Mode discovery and
parsing, tool moderation and the `default_action` cascade, runtime-overlay
transition handlers and atomic rollback, event payload contracts, the lean-head
guardrail pins shipped by `d7f5f2e`, and docs parity. The "zero tests → wire an
import smoke and label it" branch of the item does **not** apply here.

### 2.3 Two installation facts, measured before the workflow was written

- **Both modules are installed for both test jobs.** `hooks-mode`'s suite
  imports `amplifier_module_tool_mode` (`test_list_modes_all.py::test_tool_mode_handle_list_filters_to_advertised_only`).
  Installing only the module under test fails that one test with
  `ModuleNotFoundError` — observed locally, then designed around, not guessed.
- **`amplifier-core` and `amplifier-foundation` are supplied by CI and FLOAT.**
  Neither module's `pyproject` declares them; in production the host process
  supplies them, and CI is not a host process. Pinning rule applied: pin the
  tools that **define** the gate (ruff 0.16.6, pytest 9.1.1, pytest-asyncio
  1.4.0); float the peer dependencies **under test**, because a real break
  against current core/foundation showing up red is the entire point.
  `tool-mode` also gets `amplifier-core` so CI exercises the **real**
  `ToolResult` rather than the module's local fallback stub.

### 2.4 setup-uv without a cache input

`enable-cache: true` keys the cache on `**/uv.lock`; only `modules/tool-mode`
commits one. A sibling lane observed that hard-fail a red-proof run at setup,
before any check ran — a red that proves nothing. (`enable-caching:` is not a
valid input at all and is silently ignored, which is worse.) The cache input is
omitted entirely and the reason is recorded in the workflow.

---

## 3. The red-then-green gate

### 3.1 RED — run [34156524100](https://github.com/microsoft/amplifier-bundle-modes/actions/runs/34156524100)

Scratch branch `ci/red-proof-j1e6` = this branch + one commit planting **three
deliberate, independent defects**, so each red job fails for **its own** reason
rather than all of them for one:

```
failure  Tests -- hooks-mode (py3.11)   1 failed, 297 passed in 1.05s
failure  Tests -- hooks-mode (py3.13)   1 failed, 297 passed
failure  Lint                            F401 `json` imported but unused
failure  Bundle structure (YAML)         behaviors/zz-ci-red-proof.yaml:
                                           while parsing a flow sequence
success  Tests -- tool-mode (py3.11)     53 passed
success  Tests -- tool-mode (py3.13)     53 passed
```

**The test job's log shows the real suite executing**, which is the whole point
of this gate — 18 packages installed, both modules built, `amplifier-foundation`
built from git, then collection, then a genuine `AssertionError`:

```
Installed 18 packages in 20ms
........F...............................................................  [ 24%]
...
E   AssertionError: DELIBERATE FAILURE (ci/red-proof-j1e6): if you are reading
    this in a CI log, the test job is executing the real suite and gating on it.
1 failed, 297 passed in 1.05s
```

A setup error or a lint error would have produced a red run that proved nothing.
`Tests -- tool-mode` staying **green** is the second half of the proof: the
matrix is genuinely per-module, not one blanket job whose failure says nothing
about which suite ran.

Full logs: `evidence/red-run-34156524100.txt`.

### 3.2 GREEN — run [34156650604](https://github.com/microsoft/amplifier-bundle-modes/actions/runs/34156650604)

All six checks green on `2ebb51c`. Full logs: `evidence/green-run-34156650604.txt`.

### 3.3 Scratch PR closed, branch deleted — verified by remote read

```
$ gh pr close 31 ...            ✓ Closed pull request #31
$ git push origin --delete ci/red-proof-j1e6
$ git ls-remote --heads origin ci/red-proof-j1e6
                                (0 lines)
$ gh pr view 31 --json state    CLOSED
```

The remote read is the evidence, not the tool's success message. A sibling lane
recorded `gh pr close --delete-branch` reporting a successful close while its
branch deletion silently aborted; trusting the message would have left the
scratch branch on the remote.

---

## 4. STOP AND REPORT — clean main was RED, five ways

Standing the gate up locally at `d7f5f2e` (main HEAD) found **two failing tests
and three ruff findings, all of which have been on main for months**. Each is
fixed at the source as a separate, named commit — never by weakening the
workflow, never by narrowing the rule selection, never with a `noqa`.

Baseline transcript: `evidence/clean-main-RED-baseline.txt`.

```
== ruff 0.16.6 check --isolated --select E4,E7,E9,F . ==
modules/hooks-mode/tests/test_b3_false_positive_fix.py:201:9:  F841 unused local `result`
modules/hooks-mode/tests/test_mode_author_agent.py:11:8:       F401 `pytest` imported but unused
modules/hooks-mode/tests/test_token_cost_when_inactive.py:48:1: E402 import not at top of file
Found 3 errors.

== pytest modules/hooks-mode ==   1 failed, 296 passed
== pytest modules/tool-mode  ==   1 failed,  52 passed
```

### 4.1 Both test failures are the same shape

**A deliberate behaviour change updated one test file and missed another.** In
each case the repo holds **two tests asserting contradictory contracts**, and
the *passing* one is the shipped truth — which is how the stale one survived:
whoever ran the suite saw a familiar red and moved on, because nothing gated.

| | hooks-mode | tool-mode |
|---|---|---|
| Stale test | `test_token_cost_when_inactive.py::test_inactive_session_provider_request_returns_continue` | `test_tool_mode.py::TestClearedEvent::test_clear_active_mode_emits_mode_cleared` |
| Written | `afe4884`, 2026-05-09 | `0965a4e`, 2026-04-30 |
| Superseded by | `84e3054`, 2026-05-20 | `41c3e41`, 2026-05-09 |
| That commit updated | `test_hooks.py` | the `mode:activated` and `mode:changed` tests |
| …and missed | this file | this test |
| Contradicting test that PASSES | `test_hooks.py::test_no_active_mode_injects_status_reminder` | `test_off_to_on_emits_mode_activated` |

**hooks-mode.** `84e3054` ("inject positive mode-status reminder when no mode is
active") deliberately replaced silence with a positive signal so the LLM cannot
make false claims about mode state across turns. The shipped block is observable
in any live Amplifier session as `<system-reminder source="mode-status">`.

**tool-mode.** `41c3e41` ("align tool-mode event payloads with handler contract")
added a canonical `"name"` key to all three transition payloads because
`hooks-mode`'s handlers read `"name"` **first**, and every real activation was
otherwise returning early and silently skipping the overlay machinery.
**Asserting the legacy-only payload asserts the exact bug that commit fixed.**

### 4.2 Neither fix weakens its test

- The mode-status test asserted an **absence** (`action == "continue"`); it now
  asserts a **bound** — `context_injection` equal to the fixed 176-char block
  **byte for byte**, plus `ephemeral is True`. Strictly stronger: a mode body, a
  schema reference, or a per-mode listing leaking into an inactive session now
  fails here instead of silently costing every turn of every session that never
  activates a mode.
- The `mode:cleared` test keeps **exact dict equality** — no softening to a
  subset check — and simply names both keys, so dropping either one still fails.
  The comment records why both exist, so the next reader does not "fix" the
  emitter back down to one key.

**No source file is touched by any of the five fixes.** 350 passed, was 348
passed / 2 failed.

### 4.3 `docs/events.md` was stale in the same way (`95cface`)

Exposed by the `mode:cleared` failure: the doc still described the **single-key**
payloads `41c3e41` replaced, for **all three** transition events. Not cosmetic —
a reader who trusts it and "simplifies" the emitter back to one key reintroduces
the defect. Documentation only; no source, no test, no behaviour change.

---

## 5. Landing

PR #32 opened as a **draft**, marked **ready for review** once run 34156650604
came back green on all six checks. **NOT merged** — procedure 4 forbids it, and
the merge is the manager's next stage. After merging, confirm `main` HEAD
reports a successful check-run (`gh api repos/microsoft/amplifier-bundle-modes/commits/main/check-runs`):
**configured is not installed.**

---

## 6. Reported, deliberately NOT fixed here

Three things sit just outside this gate. Absorbing them silently into a CI PR
would be the wrong call, so each is named in the PR body instead:

1. **ruff's FULL modern default tier reports 29 findings** at this head (largely
   `G201`-class logging style in source). The gate carried here is the classic
   `E4,E7,E9,F` tier, matching the sibling bundles wayfinder and browser-tester.
2. **`ruff format --check` reports 9 files would be reformatted.** Reformatting
   source is not a CI PR's job.
3. **65 `.pyc` files are committed** under `modules/*/__pycache__/`. Running the
   suite dirties tracked files — a real hazard for anyone working in this repo,
   and one this lane had to work around on every local run. Deleting them plus a
   `.gitignore` entry is a small, separate change; it is not smuggled in here.

---

## 7. Findings for the sibling CI lanes

1. **A repo with no CI can carry a red suite for months and nobody learns.** Two
   failing tests, both dating from May, both surviving a lane (`3ahq`) that ran
   the suite and *recorded the failures in its own committed evidence* as the
   pre-existing baseline. Without a gate, "1 failed" reads as the normal state of
   the world. **Expect clean main to be red in these 19 repos, and budget for it
   — it is the norm, not the exception.**
2. **Look for CONTRADICTING tests, not just failing ones.** Both failures here
   were resolvable without judgment calls because another test in the same repo
   already asserted the shipped contract. When two tests disagree, the passing
   one plus the commit message that introduced it tells you which side is stale.
   Neither needed a source change.
3. **Prove the red per JOB KIND, not per run.** Three deliberate defects in one
   scratch commit gave three independent reds plus two greens in the same run.
   The two green `tool-mode` jobs are what prove the matrix is per-module; a
   single blanket failure would not have.
4. **`--with <relative path>` works from `working-directory`.** `../hooks-mode`
   and `../tool-mode` resolve for both matrix legs, so one uniform command line
   serves every module in a `modules/`-carrying bundle without per-module
   branching.
5. **Cross-module test imports are invisible until you install only one module.**
   `hooks-mode`'s suite imports `tool-mode`. Installing per-module in isolation —
   the obvious reading of "per-module install + pytest" — turns that into a
   `ModuleNotFoundError` that looks like a broken workflow rather than a real
   coupling. Check for cross-imports before writing the matrix.

---

## 8. Spend ledger

| Item | Amount |
|---|---|
| Authority for this item | **$0.00** (`0 runs × 0 arms × $0 / 1.00 = $0.00`) |
| API calls | $0.00 |
| DTU / containers | $0.00 — none created |
| **Total** | **$0.00** |

The authority states its arithmetic and closes: this is a CI lane, it buys no
runs, and CI minutes are outside the priced envelope. No residue, nothing the
cap could not buy, nothing recorded NOT-POSSIBLE.

**Infrastructure: none created.** Nothing registered in the infra ledger,
nothing claimed, nothing to tear down. `infra_ledger.sh ... sweep` was never
run (it is the manager's batch-close verb).

---

## 9. Goal defect, recorded per procedure

**This item is one item with nineteen lanes, but the per-lane goal applies a
single-lane claim/resolve procedure to it.** `work_claim` was refused —
`model_performance-j1e6` is held by `agent-spark-1-1101253` and was resolved at
2026-09-07T18:14:01Z covering one repo (wayfinder) — and Procedure 1 reads that
refusal as outcome branch C (write `BLOCKED.md`, stop). Taken literally, all 19
CI lanes would have produced 19 `BLOCKED.md` files and no CI, over a claim
refusal that is the **designed steady state** of a one-item/many-lanes item.

This lane did what the `j1e6-ci-browser-tester` sibling did and recorded as a
defect first: read the authoritative spec with `work_list(item_id=…)`, which
returns the full description and acceptance criteria **without claiming**,
completed every deliverable, and recorded the per-repo result with
`work_erratum` (append-only, needs no claim, never rewrites the stored
resolution). Choosing branch C here would have been a false BLOCKED.

**Recommended fix for the next multi-lane item:** either file one item per repo,
or have the goal say — *claim if free; if a sibling holds it, proceed and record
per-repo completion via `work_erratum`, and let the holder or the manager resolve
once every lane has landed.*
