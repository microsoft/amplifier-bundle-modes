# Amplifier Mode Schema Reference

> **Contributed by `/mode-design`** — This file is loaded only when `/mode-design` is
> active. When the mode is off, zero tokens from this document are consumed. That is the
> token-savings story: weighty reference material that costs nothing until a human
> explicitly asks for it.

---

## Table of Contents

1. [File Location and Naming Conventions](#1-file-location-and-naming-conventions)
2. [Top-Level Frontmatter Fields](#2-top-level-frontmatter-fields)
3. [The `tools` Policy Block](#3-the-tools-policy-block)
4. [Mode Body Conventions](#4-mode-body-conventions)
5. [The `contributes` Block (v1)](#5-the-contributes-block-v1)
6. [v1.1 Contribution Preview: `tools` and `config`](#6-v11-contribution-preview-tools-and-config)
7. [Activation, Deactivation, and Overlap — Refcount Semantics](#7-activation-deactivation-and-overlap--refcount-semantics)
8. [Authoring Checklist](#8-authoring-checklist)
9. [Common Patterns](#9-common-patterns)
10. [Anti-Patterns](#10-anti-patterns)
11. [Reading the Source Pointers](#11-reading-the-source-pointers)

---

## 1. File Location and Naming Conventions

Mode files are Markdown files with YAML frontmatter. The runtime discovers them by scanning
directories in a fixed precedence order.

### 1.1 Discovery Paths (Highest Precedence First)

| Priority | Location | Owner |
|----------|----------|-------|
| 1 (highest) | `<project-root>/.amplifier/modes/*.md` | Project author |
| 2 | `~/.amplifier/modes/*.md` | End user |
| 3 | `<bundle-root>/modes/*.md` | Bundle author |
| 4 | Explicit `search_paths` in `hooks-mode` config | Operator/deployer |
| 5 (lowest) | Composed bundle `modes/` directories | Other included bundles |

> **Server note.** In server deployments, "project root" is determined by the
> `session.working_dir` capability, not the server process `cwd`. This enables correct
> mode resolution when Amplifier runs as a backend service.

### 1.2 Naming Rules

- Files must use the `.md` extension. Other extensions are silently skipped.
- The filename stem is the **fallback name** when `mode.name` is omitted.
- Convention: lowercase kebab-case (e.g. `code-review`, `plan`, `systems-design`).
- When two modes across paths share the same `name`, higher-precedence wins; lower is
  silently ignored.
- Third-party bundle modes should use descriptive, namespaced names (`perf-audit` not
  `perf`; `systems-design` not `design`).

### 1.3 Shortcut Collision Resolution

When two modes claim the same `shortcut`, first-encountered-in-precedence-order wins. The
losing mode is still activatable via `/mode <name>`. An `INFO` log is emitted, but no
error is raised to the user.

### 1.4 Structural Discovery: How `modes/` Gets Scanned

A bundle's `modes/` directory is scanned **automatically when any piece of that bundle
is composed into a session**. There is no `modes:` field anywhere — the directory is
discovered by convention based on its location within a composed bundle.

This is what makes near-empty install-anchor behaviors viable. A pure install anchor —
no `context.include`, no `agents`, no `tools`, no `hooks` — looks like this:

```yaml
bundle:
  name: <name>-behavior
  version: 0.1.0
  description: ...
```

When a user composes this behavior via `settings.yaml`'s `app:` or `added:` list, the
runtime identifies the parent bundle (the directory containing `behaviors/<name>.yaml`)
and the modes hook scans the parent's `modes/` directory — registering every mode found
there at priority 5 above.

Result: a 4-line install-anchor behavior is enough to make a bundle's modes discoverable.
No `modes:` declaration, no explicit listing, no boilerplate.

**Reference implementations:**

- [`microsoft/amplifier-bundle-evaluation`](https://github.com/microsoft/amplifier-bundle-evaluation) —
  Thin behavior with short awareness context (~110 tokens), single `advertised: false`
  mode. The canonical lightweight example.
- [`microsoft/amplifier-bundle-llm-wiki`](https://github.com/microsoft/amplifier-bundle-llm-wiki) —
  Pure-anchor behavior (no context at all), 5 advertised workflow modes each contributing
  the same orientation file via `contributes.context`. See §9.7 for the pattern.

> **Consequence for behavior authors.** A behavior file's job is structural composition,
> not capability mounting. Heavy capability belongs in modes (`contributes`), agents
> (`delegate`), or skills (`load_skill`). The behavior file itself should be as small as
> possible. See `mode-design-discipline §1` for the symmetric "behaviors should be light"
> rule and `foundation:docs/AGENT_AUTHORING.md §"Hard policy: behavior context.include
> token budget"` for the authoritative mechanism ranking.

---

## 2. Top-Level Frontmatter Fields

Fully-annotated mode header:

```yaml
---
mode:
  # ─── Identity ─────────────────────────────────────────────────
  name: mode-name                   # Recommended. Defaults to filename stem.
  description: "What this mode does" # Shown on activation and in /modes.
  shortcut: mode-name               # Optional; defaults to name (lowercased).
                                    # Set to `false` (YAML boolean, unquoted) to disable.

  # ─── Visibility (v1) ──────────────────────────────────────────
  advertised: true                  # Default: true. false = hidden from LLM-facing listings.

  # ─── Transition Control ───────────────────────────────────────
  default_action: block             # "block" or "allow". Default: "block".
  allowed_transitions: []           # List of mode names this mode can transition TO.
                                    # Absent = any transition allowed.
  allow_clear: true                 # Default: true. false = /mode off is rejected.
  gate_policy: confirm              # Optional activation override: auto | warn | confirm.
                                    # Omitted/null inherits tool-mode module config.

  # ─── Tool Policy ──────────────────────────────────────────────
  tools:
    safe:    [...]                  # Always allowed, no friction.
    warn:    [...]                  # Blocked once with warning; retry proceeds.
    confirm: [...]                  # Requires user approval before execution.
    block:   [...]                  # Never allowed while mode is active.

  # ─── Contributions (v1) ───────────────────────────────────────
  contributes:
    agents:
      agent-name:
        source: "@bundle:agents/agent-name"
    context:
      - "@bundle:context/heavy-reference.md"
    skills:
      - "@bundle:skills/specialist-skill"
---

[Mode body — injected as system-reminder while mode is active]
```

### 2.1 `name`

**Type:** string | absent  **Default:** filename stem

The canonical identifier. This is what the user types in `/mode <name>`. Explicit names
are strongly recommended — relying on the filename stem creates a maintenance hazard
(rename the file, silently break the mode identity).

Modes named the same as built-in CLI commands (`help`, `mode`, `modes`, `exit`, `quit`)
are valid but their default slash-alias is overridden by built-in dispatch. Assign an
explicit `shortcut:` if you need a working alias.

### 2.2 `description`

**Type:** string | absent  **Default:** empty string

Shown in the activation banner and `/modes` listing. One sentence, user-benefit oriented.
Not shown in LLM-facing listings when `advertised: false`.

### 2.3 `shortcut`

**Type:** string | `false` | absent  **Default:** `name` lowercased

| Value | Effect |
|-------|--------|
| Absent | Auto-register `/<name>` (lowercased). |
| `shortcut: my-alias` | Register `/my-alias`. |
| `shortcut: false` | Disable the slash alias. |
| `shortcut: "false"` | ⚠ String literal — registers `/false`. Use unquoted boolean. |

After lowercasing, shortcut must match `^[a-z][a-z0-9_-]*$`. Invalid shortcuts log a
warning and register no alias.

**YAML boolean trap.** `true`, `yes`, `on` in non-quoted context are YAML booleans and
will be coerced to strings, fail the pattern check, and log a warning. Only `false`
(unquoted) has meaningful semantics here.

### 2.4 `advertised` (v1)

**Type:** boolean  **Default:** `true`

Controls whether the mode appears in LLM-facing `mode(list)` output.

- `advertised: true` — mode visible to LLM and humans.
- `advertised: false` — mode hidden from LLM. Humans can still activate via slash command
  or `/modes --all` (CLI flag surfacing unadvertised modes for operators).

**Use case.** Bundle authors can package context-heavy specialist capabilities (large
reference files, specialist agents) that are completely invisible — zero token cost — until
a human explicitly activates the mode. This file is one such capability.

**Token-savings invariant.** Contributions are pre-activated at bundle load (code downloaded
and imported), but **not mounted**. Agent descriptions, context, and skills do not leak
into session context while the mode is off.

### 2.5 `default_action`

**Type:** `"block"` | `"allow"`  **Default:** `"block"`

Fallback policy for tools not explicitly listed in any `tools.*` bucket.

- `"block"` — only explicitly-listed tools are available. For focused-intent modes.
- `"allow"` — only `tools.block` items are denied; all others pass. For additive guard-rail
  modes that restrict a few dangerous operations.

> If you have `default_action: block` and a large `tools.safe` list, consider whether the
> mode is too broad. If you have `default_action: allow` and a large `tools.block` list,
> consider whether a tight `safe` list would be clearer.

### 2.6 `allowed_transitions`

**Type:** list of mode names | absent  **Default:** absent (no restriction)

When non-empty, restricts which modes can be activated from within this mode. Unlisted
transitions return a rejection message.

```yaml
allowed_transitions:
  - careful       # Can switch to careful
  - plan          # Can switch to plan
                  # All other /mode <name> attempts rejected
```

Use cases: guided workflows, high-security modes that only permit transitions to equally
secure modes, demo environments with restricted mode graph navigation.

### 2.7 `allow_clear`

**Type:** boolean  **Default:** `true`

- `true` — `/mode off` works normally.
- `false` — `/mode off` is rejected. User must transition to a named mode or restart.

**Caution.** `allow_clear: false` without `allowed_transitions` traps the user in the mode
for the session lifetime. Always provide an escape route.

### 2.8 `gate_policy`

**Type:** `"auto"` | `"warn"` | `"confirm"` | null | absent

**Default:** absent (inherit tool-mode module configuration, which defaults to `warn`)

Controls agent-initiated `mode(set)` activation of this **target** mode. `auto`
activates immediately; `warn` denies the first attempt and permits retry; `confirm`
requests a human decision from the host's `coordinator.approval_system` service.
Confirmation is required if either the target or module specifies `confirm`.
Invalid types or values log a warning and require confirmation rather than falling
through to a lower-precedence mode definition.

For `confirm`, tool-mode awaits `request_approval(prompt, options=["Allow", "Deny"],
timeout=60.0, default="deny")`, also bounded by `asyncio.wait_for(..., timeout=60.0)`.
Only the string `Allow` permits activation. Missing service/provider, denial,
unexpected responses, exceptions, and timeout return `success: false` with
`status: denied` and a reason. No activation/change event or contribution effect
occurs before approval; if the active mode changed while waiting, activation is
denied. Caller-supplied approval fields and previous warnings are not approval.
There is no approval cache or automatic retry permission: every attempt needs a
fresh host decision.

This field does not change outgoing `allowed_transitions`, `allow_clear`, the
module-level clear gate, active-mode `tools.confirm`, listing visibility, or human
slash-command activation. The module-level `confirm` clear gate still denies
agent clearing; it does not request approval.

---

## 3. The `tools` Policy Block

Every tool call passes through the mode hook which consults this block before allowing
execution.

### 3.1 The Four Buckets

```yaml
tools:
  safe:
    - read_file       # Works normally, no friction.
    - grep

  warn:
    - bash            # First call blocked with warning. LLM may retry.
                      # Second call proceeds. Resets at session end or mode off.

  confirm:
    - write_file      # Triggers approval system: user is prompted before execution.
    - edit_file       # Approval is per-call, not per-tool-type.

  block:
    - deploy          # Immediate rejection. No retry. Only /mode off can unblock.
```

**Policy resolution.** If a tool appears in multiple buckets (configuration error), the
most restrictive wins: `block` > `confirm` > `warn` > `safe`.

### 3.2 How `warn` Works

1. First call: blocked. LLM receives:
   `"[mode: <name>] Tool '<tool>' is available but requires acknowledgement. Call again to proceed."`
2. LLM explains intent, retries.
3. Second call: proceeds normally.
4. Warn state resets per session (not per call).

`warn` is a UX control, not a security control. It creates one moment of intentionality.
Autonomous agents will simply retry.

### 3.3 How `confirm` Works

1. Mode hook flags tool in `session_state.require_approval_tools`.
2. Approval hook prompts: `"[confirm] The assistant wants to run <tool>. [Y/n]"`
3. Execution waits for user response.
4. Approved: tool runs. Denied: LLM receives rejection.
5. Approval is per-call — each `write_file` call prompts again.

### 3.4 Infrastructure-Tool Bypass: `mode` and `todo`

**`mode` tool** is never blocked by the mode's tool policy. An agent inside a restrictive
mode can always call `mode(operation="list")` or `mode(operation="set", name="...")`. The
tool-mode activation gate applies independently: the target mode's `gate_policy`
overrides the module-level default (`warn`). See §2.8. Clear keeps the module-level gate.

**`todo` tool** bypasses mode policy and is always available even when `default_action:
block` and `todo` is not in `tools.safe`. Task list operations are meta-operations on the
conversation, not actions in the user's system. Bundle authors who explicitly want to block
`todo` can list it in `tools.block`.

### 3.5 Unlisted Tools and `default_action`

- With `default_action: block`: `"[mode: <name>] Tool '<tool>' is not available in this mode."`
- With `default_action: allow`: tool proceeds without restriction.

A common mistake: `default_action: block` with a `tools.safe` list missing tools the LLM
needs for the primary task. The result is confusing repeated denials. See §8 for the
authoring checklist to catch this.

---

## 4. Mode Body Conventions

Everything after the closing `---` of the YAML frontmatter is the **mode body**. It is
injected into conversation context as a `<system-reminder>` block each turn while active.

### 4.1 Injection Format

```
<system-reminder source="mode-NAME">
[mode body content]
</system-reminder>
```

The `source` attribute identifies the active mode. Multi-mode scenarios (future) produce
multiple `<system-reminder>` blocks.

### 4.2 Writing Effective Mode Bodies

**Lead with intent.** First line: `PLAN MODE: Analyze, research, and plan — but do NOT
implement.` Front-load the mode's purpose.

**Use DO / DO NOT structure.** Explicit separation is more reliable than prose:
```markdown
Do NOT:
- Write or modify files
- Execute commands that change state

You CAN:
- Run analysis tools (python_check, LSP)
- Delegate to specialist agents
```

**Include format guidance.** If the mode expects a specific output format (plans, reports,
checklists), describe it. This makes every response in the mode consistent.

**Keep bodies focused.** The mode body is injected every turn. A 2,000-token body in a
20-turn session = 40,000 tokens of overhead. Design with awareness of per-turn cost.

**Include exit guidance.** End with how to leave: `Use /mode off when complete.` or
`Use /implement when the plan is approved.`

### 4.3 `@`-Mention Inline Expansion

Mode bodies support `@bundle:path` mentions expanded at **load time** (session startup):

```yaml
---
mode:
  name: code-review
  ...
---

CODE REVIEW MODE: Systematic review with project standards.

@my-bundle:context/code-standards.md
@my-bundle:context/security-checklist.md
```

Referenced files are read and inlined into the mode body. This separates the mode skeleton
from its reference content. Note: expansion happens at load, not activation — file changes
after session start are not reflected.

For very large documents, prefer `contributes.context` over inline `@`-mentions to avoid
per-turn injection cost.

---

## 5. The `contributes` Block (v1)

`contributes` allows a mode to **lazily mount** additional capabilities — agents, context,
skills — that are invisible to the LLM when the mode is off and available when active.

### 5.1 Shape

```yaml
contributes:
  agents:
    mode-design-expert:
      source: "@bundle:agents/mode-design-expert"
    specialist:
      source: "@other-bundle:agents/specialist"

  context:
    - "@bundle:context/mode-schema-reference.md"
    - "@bundle:context/worked-examples.md"

  skills:
    - "@bundle:skills/mode-design-skill"
    - "@other-bundle:skills/domain-skill"
```

The shape mirrors bundle frontmatter `agents`/`context`/`skills`. This lets the existing
`merge_module_lists` / `deep_merge` stack handle overlap reconciliation without modification.

### 5.2 Pre-Activation at Bundle Load Time

At session startup, `Bundle.prepare()` walks all discovered modes' contributions and
pre-activates them: code is downloaded, installed, and imported, but **not mounted**. No
agent descriptions, context, or skills are visible to the LLM.

Pre-activation ensures first activation is fast (no cold-start download). The tradeoff:
all modes' contributions are pre-activated even if never used. For most deployments this
cost is acceptable. True lazy activation (deferred to first use) is a non-goal for v1.

### 5.3 `contributes.agents`

Mounts agents into the coordinator's registry while the mode is active, making them
available via the `delegate` tool.

```yaml
contributes:
  agents:
    mode-design-expert:
      source: "@modes-bundle:agents/mode-design-expert"
```

**Referential integrity rule.** If `contributes.agents` is non-empty, `delegate` must be
reachable via tool policy:
- `delegate` in `tools.safe`, OR
- `delegate` in `tools.warn`, OR
- `default_action: allow`

If violated, parse-time linter emits:
```
WARN: mode 'mode-name' contributes agents but delegate is not reachable via tool policy.
```
Mode still loads; the contributed agents are mounted but unreachable.

### 5.4 `contributes.context`

Contributes context files to the LLM context while the mode is active. On activation,
each listed file is automatically resolved and its content is injected into the
`<system-reminder>` block — prepended to the mode body — on every provider request.
The mode body does **not** need to contain an explicit `@`-mention of the file; the
injection is handled automatically by the context pipeline. On deactivation, the
contributed content is removed.

```yaml
contributes:
  context:
    - "@modes-bundle:context/mode-schema-reference.md"   # This file
    - "@modes-bundle:context/design-examples.md"
```

**Injection order:** contributed context files first (in declaration order), then the
mode body — all within a single `<system-reminder>` block.

**Token cost:** zero when the mode is inactive. The reference material is only injected
on provider requests while the mode is active, making `contributes.context` ideal for
`advertised: false` modes that carry heavy reference files without burdening every
session.

### 5.5 `contributes.skills`

Contributes skills to the active skill registry, making them available via `load_skill`.

```yaml
contributes:
  skills:
    - "@modes-bundle:skills/mode-design-reference"
```

**Referential integrity rule.** If `contributes.skills` is non-empty, `load_skill` must be
reachable via tool policy (same rule as `delegate` for agents).

### 5.6 Contribution Lifecycle and Atomic Rollback

**On activation (atomic):**
1. Validate schema; resolve `@`-mention sources.
2. Compute delta: new items vs. items already in session.
3. New items: `coordinator.mount(category, name, instance, config)`.
4. Overlapping items: increment refcount; deep-merge configs (mode's config wins per-key);
   existing instance is **not replaced**.
5. Push `config` overlay entries.
6. Inject mode body and contributed context.
7. Persist `active_mode` to session state.
8. **On any failure in steps 3–5:** unmount everything mounted in this transition, pop
   everything pushed, mark mode inactive, emit `mode:activation_failed` with the failing
   item identified. This is the **atomic rollback guarantee**.

**On deactivation:**
1. Decrement refcount per contributed item; if `0`, unmount.
2. Pop config overlay entries for this scope.
3. Remove mode body and contributed context injections.
4. Clear `active_mode` from session state.
5. Emit `mode:transition_completed` with the unmount delta.

---

## 6. v1.1 Contribution Preview: `tools` and `config`

These blocks are reserved in the schema for v1.1. **Do not use in production modes.**

### 6.1 `contributes.tools` (v1.1, deferred)

```yaml
contributes:
  tools:
    - module: custom-tool-module
      source: git+https://github.com/org/amplifier-module-custom-tool
      config:
        timeout: 30
```

Allows a mode to mount additional tool modules while active. Deferred because
auto-adding contributed tools to the effective safe list requires a small kernel change
to policy evaluation order.

### 6.2 `contributes.config` (v1.1, deferred)

```yaml
contributes:
  config:
    orchestrator.config.model: claude-opus-4
    session.max_tokens: 64000
```

Allows a mode to push config overlay entries. Last-pushed-wins for scalar values; mode's
entries win over session baseline; popped on deactivation. Deferred while overlay
semantics (merge rules for nested structures, observable precedence) are finalized.

---

## 7. Activation, Deactivation, and Overlap — Refcount Semantics

The refcount model ensures items shared between session baseline and multiple modes are
never incorrectly unmounted.

### 7.1 The Refcount Model

Every contribution item (agent, context file, skill) has an integer refcount:

- **Session baseline** contributes `+1` to every item declared in `bundle.md`.
- Each **active mode** contributes `+1` to every item in its `contributes.*`.

**Mount:** only at refcount `0 → 1`.  
**Unmount:** only at refcount `1 → 0`.  
At any refcount `> 1`: mount/unmount is a no-op.

### 7.2 Overlap Scenario Matrix (S1–S4)

#### S1 — Item in session baseline AND in mode

| Event | Refcount | Action |
|-------|----------|--------|
| Session start | 1 | Mounted (baseline) |
| Mode activates | 2 | No-op (already mounted) |
| Mode deactivates | 1 | No-op (still needed by session) |
| Session ends | 0 | Unmounted |

**Result:** Mode activation/deactivation has no effect on the item. Config deep-merge
applies for the duration of the mode's activation.

#### S2 — Item only in mode (not in session baseline)

| Event | Refcount | Action |
|-------|----------|--------|
| Session start | 0 | NOT mounted |
| Mode activates | 1 | Mounted (fresh mount) |
| Mode deactivates | 0 | Unmounted |
| Session ends | — | Already unmounted |

**Result:** Item is exclusively mode-managed. Appears on activation; disappears on
deactivation. This is the core use case for `advertised: false` specialist modes.

#### S3 — Item in Mode M1 AND Mode M2, not in session baseline

| Event | Refcount | Action |
|-------|----------|--------|
| Session start | 0 | NOT mounted |
| M1 activates | 1 | Mounted |
| M1 deactivates, M2 activates | 1→0→1 | Unmount, then re-mount (brief churn) |
| M2 deactivates | 0 | Unmounted |

> **Known v1 limitation.** The brief unmount/remount when switching between modes that
> share a contribution causes a short availability gap. A cross-mode transition
> optimization computing net delta is planned for v1.1.

#### S4 — Item in session baseline AND in both M1 and M2

| Event | Refcount | Action |
|-------|----------|--------|
| Session start | 1 | Mounted (baseline) |
| M1 activates | 2 | No-op |
| M1 deactivates, M2 activates | 2→1→2 | No-op both times |
| M2 deactivates | 1 | No-op |
| Session ends | 0 | Unmounted |

**Result:** Item is always mounted; zero churn across all mode transitions.

### 7.3 Atomic Rollback on Activation Failure

If any activation step fails, the runtime automatically rolls back:

1. Unmount everything mounted in this transition.
2. Pop all config overlay entries pushed in this transition.
3. Mark mode inactive; `session_state.active_mode` unchanged.
4. Emit `mode:activation_failed` identifying the failing item.
5. LLM receives: `"[mode] Activation of '<name>' failed: <reason>. Mode is not active."`

Rollback is best-effort: secondary failures during rollback are logged and remaining items
are processed. The session continues in its pre-activation state.

**Implication for authors.** Contributions sourced from external git URLs can cause
activation failures in degraded network conditions. Prefer sources pre-activated
successfully at session startup for resilient modes.

---

## 8. Authoring Checklist

Use before committing a mode file. Every box must be checked.

### 8.1 Identity and Discovery

- [ ] `name:` is set explicitly.
- [ ] Name uses lowercase kebab-case; is unique in the expected deployment scope.
- [ ] `shortcut:` set if you need a specific alias; default-from-name verified to not
      conflict with built-in CLI commands or other bundle modes.
- [ ] `description:` is one sentence, user-benefit oriented.
- [ ] If `advertised: false`, description is still accurate for power users.

### 8.2 Tool Policy Coherence

- [ ] Every tool the LLM needs for the primary task is in `tools.safe` or `tools.warn`.
- [ ] If `default_action: block`: run through a mental simulation — every tool the LLM
      would call is explicitly enumerated.
- [ ] `delegate` is in `tools.safe` or `tools.warn` if the LLM will call agents.
- [ ] `load_skill` is in `tools.safe` or `tools.warn` if the LLM will use skills.
- [ ] `mode` and `todo` do not need to be listed (bypass mode policy by default).
- [ ] `confirm` is limited to truly dangerous, irreversible operations.
- [ ] `block` is reserved for tools that must never execute in this mode.

### 8.3 Contributions

- [ ] `contributes.agents` non-empty → `delegate` reachable via tool policy.
- [ ] `contributes.skills` non-empty → `load_skill` reachable via tool policy.
- [ ] All referenced files (`agents.*.source`, `context.*`, `skills.*`) exist.
- [ ] Total contributed context size is appropriate for the per-turn injection budget.

### 8.4 Mode Body

- [ ] Leads with clear statement of intent.
- [ ] DO / DO NOT sections are explicit.
- [ ] `@bundle:path` mentions resolve to existing files.
- [ ] Body includes an exit hint (`Use /mode off...` or next transition).

### 8.5 Transitions and Guards

- [ ] `allow_clear: false` is intentional and provides `allowed_transitions` escape route.
- [ ] `allowed_transitions` is exhaustive for the mode's intended workflow.

### 8.6 Final Verification

- [ ] Activate mode in test session; attempt the primary task.
- [ ] Verify unlisted tools are blocked (try calling one).
- [ ] Verify `warn` tools produce warning on first call.
- [ ] If `contributes.*` non-empty: verify contributed items appear post-activation.
- [ ] Mode appears / does not appear in `/modes` per the `advertised` setting.

---

## 9. Common Patterns

### 9.1 Read-Only Analyst

**Goal:** Hard guarantee of zero side effects. Investigation only.

**Design:** `default_action: block` with only read tools in `safe`. No `bash`, no write
tools — not even in `warn`. Completely prevents accidental state changes.

```yaml
---
mode:
  name: explore
  description: Zero-footprint exploration — understand before acting
  shortcut: explore

  tools:
    safe:
      - read_file
      - glob
      - grep
      - web_search
      - web_fetch
      - load_skill
      - LSP

  default_action: block
---

EXPLORE MODE: Understand the codebase with zero side effects.

Your role:
- MAP the codebase structure
- TRACE code paths and dependencies
- ANSWER questions about how things work

Do NOT:
- Modify files or execute commands
- Create todos or delegate to other agents
- Make any changes whatsoever

Output format:
```
#### Structure
[Directory/module overview]

#### Key Files
- path/file.py: Purpose

#### Flow
[How data/control flows]

#### Notes
[Observations, patterns, concerns]
```

Use /mode off when exploration is complete.
```

**Variant — with delegation.** To allow multi-agent investigation without write capability,
add `delegate` to `tools.safe` and list specialist agents in `contributes.agents`.

### 9.2 Write-With-Friction

**Goal:** Full capability with mandatory user checkpoint before every write or command.
For high-stakes or unfamiliar-codebase work.

**Design:** Read operations in `safe` (no friction). Write operations and `bash` in
`confirm` (approval prompt per call). Mode body prompts LLM to present intent before
acting, since users will be reviewing each action.

```yaml
---
mode:
  name: careful
  description: Full capability with confirmation for destructive actions
  shortcut: careful

  tools:
    safe:
      - read_file
      - glob
      - grep
      - web_search
      - web_fetch
      - load_skill
      - LSP
      - python_check
      - todo
      - delegate
      - recipes
    confirm:
      - write_file
      - edit_file
      - bash

  default_action: block
---

CAREFUL MODE: Work normally, but confirm before destructive actions.

Read and analyze freely. When ready to modify files or run commands, describe your
intent clearly — the approval system will prompt the user before each action.

Best for: production config changes, security-sensitive code, unfamiliar codebases.

Use /mode off to disable confirmations and work at full speed.
```

**Lighter variant — warn-before-write.** Replace `confirm` with `warn` for one
acknowledgement per tool type per session rather than one prompt per call. Useful when
full per-call confirmation creates workflow friction.

### 9.3 Specialist with Hidden Capabilities

**Goal:** Package a context-heavy specialist mode — reference documents, specialist agents,
domain skills — that is completely invisible to the LLM until a human activates it. Zero
token cost at rest; full capability on activation.

**Design:**
- `advertised: false` hides from LLM-facing listings.
- `contributes.context` includes heavy reference files.
- `contributes.agents` includes specialist agents.
- `contributes.skills` includes domain skills.
- Tool policy makes `delegate` and `load_skill` reachable (required for contributions).
- Mode body is brief; heavy detail is in contributed context files.

```yaml
---
mode:
  name: mode-design
  description: Author and review Amplifier mode files with full schema reference
  shortcut: mode-design
  advertised: false          # Hidden from LLM — humans activate via /mode-design

  tools:
    safe:
      - read_file
      - glob
      - grep
      - web_search
      - web_fetch
      - load_skill           # Required: contributes.skills non-empty
      - LSP
      - python_check
      - todo
      - delegate             # Required: contributes.agents non-empty
      - recipes
    warn:
      - write_file
      - edit_file
      - bash

  default_action: block

  contributes:
    agents:
      mode-design-expert:
        source: "@modes-bundle:agents/mode-design-expert"
    context:
      - "@modes-bundle:context/mode-schema-reference.md"    # This file
    skills:
      - "@modes-bundle:skills/mode-design-skill"
---

MODE DESIGN MODE: Author, review, and validate Amplifier mode files.

The full mode schema reference is available in context. The mode-design-expert
agent is available via delegate for complex authoring questions.

When authoring: follow §8 Authoring Checklist.
When reviewing: check tool policy coherence, contribution referential integrity,
mode body clarity, and transition guard intentionality.

Use /mode off when design work is complete.
```

### 9.4 Permissive Overlay (Block-One Pattern)

**Goal:** Normal capability but one specific tool disabled. Rather than listing all safe
tools, use `default_action: allow` and block only the dangerous one.

**Design:** `default_action: allow` with only the blocked tool in `tools.block`. Everything
else passes through.

```yaml
---
mode:
  name: no-deploy
  description: Normal capability, but deployment commands are blocked
  shortcut: no-deploy

  tools:
    block:
      - deploy
      - push-to-prod

  default_action: allow    # Everything NOT in block passes through
---

NO-DEPLOY MODE: All normal capabilities active except deployment.

deploy and push-to-prod are blocked. All other tools function normally.

Use /mode off to restore full capability including deployment.
```

**When to use.** `default_action: allow` is for guard-rails (block a few dangerous things).
`default_action: block` is for focus lenses (only allow specific things). Choose based on
whether the mode is additive restriction or selective permission.

### 9.5 Plan-Then-Execute Workflow Pair

**Goal:** Enforce a separation between analysis and implementation phases. `plan` mode does
research; `implement` mode has write capability. The transition from plan to implement is
explicit, creating a clear planning-approval checkpoint.

```yaml
---
mode:
  name: plan
  description: Analyze, strategize, and organize — but don't implement
  shortcut: plan

  tools:
    safe:
      - read_file
      - glob
      - grep
      - web_search
      - web_fetch
      - load_skill
      - LSP
      - python_check
      - todo
      - delegate
      - recipes
    warn:
      - bash

  default_action: block
  allowed_transitions:
    - implement
  allow_clear: false        # Must explicitly move to implement; can't skip to modeless
---

PLAN MODE: Analyze, research, and plan — do NOT implement.

Output a structured implementation plan. Use /implement when the plan is approved.
```

```yaml
---
mode:
  name: implement
  description: Execute the approved plan — full write capability
  shortcut: implement

  tools:
    safe:
      - read_file
      - glob
      - grep
      - write_file
      - edit_file
      - bash
      - apply_patch
      - load_skill
      - LSP
      - python_check
      - todo
      - delegate
      - recipes

  default_action: block
  allowed_transitions:
    - plan
  allow_clear: true         # Can exit when work is done
---

IMPLEMENT MODE: Execute the approved plan.

Full write capability. Follow the plan from plan mode.
Use /plan to return to planning if requirements change.
Use /mode off when implementation is complete.
```

### 9.6 Gated Security Audit

**Goal:** Deep code investigation for security analysis, with read-only guarantee and
specialist security agents. Hidden from casual LLM view (security tooling adds token cost).

```yaml
---
mode:
  name: security-audit
  description: Deep security analysis — read-only with specialized security agents
  shortcut: sec
  advertised: false

  tools:
    safe:
      - read_file
      - glob
      - grep
      - web_search
      - web_fetch
      - load_skill
      - LSP
      - delegate

  default_action: block
  allow_clear: true

  contributes:
    agents:
      security-guardian:
        source: "@foundation:agents/security-guardian"
    context:
      - "@security-bundle:context/owasp-checklist.md"
    skills:
      - "@security-bundle:skills/security-review-patterns"
---

SECURITY AUDIT MODE: Systematic read-only security review with specialist agents.

Do NOT modify any files during audit — document findings only.

Workflow:
1. Survey attack surface with read tools
2. Delegate specific checks to security-guardian
3. Compile findings
4. Use /mode off when complete; implement fixes in a separate session
```

### 9.7 Workflow Modes with Shared Orientation

**Goal:** N workflow modes that all benefit from the same orientation reference
(cross-mode transitions, project structure, shared vocabulary). Zero-cost when no mode
is active; orientation mounted while ANY of the N modes is active.

This extends §9.3 (Specialist with Hidden Capabilities) to the multi-mode workflow case.
Each mode contributes the same context file via `contributes.context`; refcount semantics
(§7.2 S3) handle mount/unmount as the user moves through the workflow.

**Behavior file** (`behaviors/wiki.yaml`) — pure install anchor (see §1.4), no
`context.include`; modes are discovered structurally:

```yaml
bundle:
  name: wiki-behavior
  version: 0.2.0
  description: Workflow modes for LLM-maintained wikis
```

**Mode files** (`modes/wiki-init.md` and the same pattern in `wiki-ingest`, `wiki-lint`,
`wiki-publish`, `wiki-query`) — each contributes the same orientation file:

```yaml
---
mode:
  name: wiki-init
  description: Set up the wiki for a new project
  advertised: true
  default_action: block

  tools:
    safe: [read_file, glob, grep, load_skill, todo, mode]
    warn: [write_file, edit_file]

  contributes:
    context:
      - "@wiki:context/wiki-instructions.md"
---

## Wiki Init Mode

**Wiki orientation auto-injected:** `@wiki:context/wiki-instructions.md` is prepended to
this mode's context — it describes the cross-mode workflow and project structure.

(... mode-specific body ...)
```

**Refcount behavior across the workflow:**

| User action | Refcount of `wiki-instructions.md` | Mounted? |
|---|---:|:---:|
| Compose bundle, no mode active | 0 | No |
| `/mode wiki-init` | 0 → 1 | Yes |
| `/mode wiki-ingest` (switching from init) | 1 → 0 → 1 | Brief churn (S3) |
| `/mode wiki-lint` (switching again) | 1 → 0 → 1 | Brief churn (S3) |
| `/mode off` | 1 → 0 | No |

The S3 brief unmount/remount during mid-workflow transitions is the known v1 cost
(see §7.2). Since the file's content is identical across all modes, the experience is
uninterrupted — the file is just reloaded on each transition.

**Reference implementation:**
[`microsoft/amplifier-bundle-llm-wiki`](https://github.com/microsoft/amplifier-bundle-llm-wiki)
runs this pattern across 5 advertised workflow modes (`wiki-init`, `wiki-ingest`,
`wiki-lint`, `wiki-publish`, `wiki-query`). When no wiki mode is active, the bundle
contributes nothing to the session's working context. Validator's verdict on the
post-refactor state: *"Zero-cost when dormant... Shared instruction context is
mode-gated via `contributes.context`, loaded only while a wiki mode is active."*

---

## 10. Anti-Patterns

### 10.1 The Empty Safe List with Block Default

**What it looks like:**
```yaml
tools:
  default_action: block
  # No safe list — every tool call fails
```

**Why it's wrong.** The LLM is paralyzed — it cannot call any tool, including read-only
investigation tools. Even in the most restrictive mode, the LLM needs read tools to do
any useful work.

**Fix:** Always enumerate the minimum tools for the primary task:
```yaml
tools:
  safe: [read_file, glob, grep, web_search, web_fetch, load_skill, LSP, todo]
  default_action: block
```

### 10.2 Contributing Agents Without Delegate Access

**What it looks like:**
```yaml
tools:
  safe: [read_file, grep]
  default_action: block
  # delegate NOT in tools.safe

contributes:
  agents:
    specialist:
      source: "@bundle:agents/specialist"
```

**Why it's wrong.** Agents are mounted but unreachable. The LLM gets a "tool not available"
error when it tries to call the agent. The parse-time linter emits a WARN but doesn't block loading.

**Fix:** Always include `delegate` in `tools.safe` when `contributes.agents` is non-empty.
Same rule: `load_skill` required when `contributes.skills` is non-empty.

### 10.3 Overloaded `confirm` (Approval Fatigue)

**What it looks like:**
```yaml
tools:
  confirm: [write_file, edit_file, bash, apply_patch, glob, grep, read_file]
```

**Why it's wrong.** Read operations never need confirmation. Confirming everything creates
approval fatigue — users approve each action mindlessly, defeating the purpose.

**Fix:** Reserve `confirm` for truly irreversible, high-impact operations. Use `warn` for
lower-risk operations. Read tools should always be `safe`.

### 10.4 The Escape-Proof Mode

**What it looks like:**
```yaml
allow_clear: false  # no allowed_transitions — user is trapped
```

**Why it's wrong.** The user cannot exit without restarting the session. Always provide
at least one escape route.

**Fix:**
```yaml
allow_clear: false
allowed_transitions:
  - careful      # Or any mode that serves as a reasonable exit point
```

### 10.5 Per-Turn Context Overload

**What it looks like:** Inlining a 200KB reference document directly in the mode body.

**Why it's wrong.** The mode body is injected every turn. A 5,000-token body in a 20-turn
session = 100,000 tokens of system-reminder overhead.

**Fix:** Put large reference files in `contributes.context` (injected via context pipeline,
not repeated system-reminder) or expose them as skills loaded on demand.

### 10.6 Shortcut Collision via Generic Names

**What it looks like:**
```yaml
mode:
  name: design
  shortcut: design   # Collides with every other bundle's "design" mode
```

**Why it's wrong.** First-loaded wins silently. The second bundle's mode loses its slash
alias with only an INFO log. Third-party bundle authors may not discover the collision.

**Fix:** Use descriptive, namespaced names:
```yaml
mode:
  name: ui-design
  shortcut: ui-design   # Specific enough to be unique
```

### 10.7 Using `shortcut: "false"` Instead of `shortcut: false`

**What it looks like:**
```yaml
shortcut: "false"   # Quoted string — registers /false as an alias
```

**Why it's wrong.** The author intends to disable the alias but the quoted string `"false"`
is treated as a shortcut name, registering `/false` — almost certainly not the intent.

**Fix:** Use the unquoted YAML boolean:
```yaml
shortcut: false   # Unquoted — disables the alias
```

### 10.8 Forgetting to Update Tool Policy When Adding Contributions

**What it looks like:** Adding `contributes.agents` to an existing mode without adding
`delegate` to the tool policy.

**Why it's wrong.** The mode worked before; after adding contributions, the LLM gets a
"tool not available" error trying to use the contributed agent. The parse-time linter warns
but doesn't prevent the mistake.

**Fix:** Whenever modifying `contributes.*`, review the entire tool policy for coherence.
Run the authoring checklist (§8.2–§8.3) after every contribution change.

### 10.9 Hidden Mode Replacing Core Functionality Without Transparency

**What it looks like:** `advertised: false` mode that blocks common operations, making the
LLM appear broken to users who don't know the mode is active.

**Why it's wrong.** Modes that restrict default behavior should be visible. Users cannot
understand why their assistant can't write files if they don't know a restrictive mode is
active. `advertised: false` is appropriate for additive specialist capabilities, not for
restrictive overlays.

**Fix:** Use `advertised: true` for modes that restrict default behavior. If a mode must
be hidden for compliance reasons, ensure the mode body clearly explains the restriction
so users see the reason when the mode IS active.

### 10.10 Mode Body Without Exit Guidance

**What it looks like:** Mode body that guides behavior but never mentions how to exit.

**Why it's wrong.** First-time users finishing a task don't know to run `/mode off`. The
session remains in a restricted mode after the intended work is done.

**Fix:** Always end the mode body with exit guidance:
```markdown
When [task] is complete, use /mode off to return to normal operation,
or /[next-mode] to proceed to the next phase.
```

---

## 11. Reading the Source Pointers

### 11.1 Mode Discovery and Parsing

**File:** `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py`

Key functions:
- `parse_mode_file(file_path)` (~lines 80–130) — Extracts YAML frontmatter, builds
  `ModeDefinition`. All frontmatter fields (`name`, `description`, `shortcut`,
  `advertised`, `default_action`, `allowed_transitions`, `allow_clear`, `gate_policy`, `tools`,
  `contributes`) are parsed here.
- `ModeDiscovery.list_modes(include_unadvertised: bool)` (~lines 310–340) — Iterates
  discovery paths, filters by `advertised` when `include_unadvertised=False`. The LLM's
  `mode(list)` calls this with `False`.
- `ModeDiscovery.get_shortcuts()` (~lines 340–360) — Builds shortcut dict. First-wins for
  collision resolution. Normalizes to lowercase. Validates against `^[a-z][a-z0-9_-]*$`.

### 11.2 Mode Activation and Tool Policy

**File:** `modules/hooks-mode/amplifier_module_hooks_mode/__init__.py`

Key functions:
- `HooksModeModule.on_tool_pre(tool_name, ...)` — Core gate. Resolves bucket (`block` →
  reject; `confirm` → set `session_state.require_approval_tools`; `warn` → return warning
  on first call; `safe` → pass; `default_action: block` → reject unlisted tools).
- `HooksModeModule.on_mode_activated(mode_name, ...)` — Handles `mode:activated` event.
  Calls `RuntimeOverlay.apply()` for contributions; injects mode body context.
- `HooksModeModule.on_mode_deactivated(mode_name, ...)` — Calls `RuntimeOverlay.revoke()`;
  removes mode body context injection.

### 11.3 The RuntimeOverlay Primitive

**File:** `[amplifier-foundation] amplifier_foundation/configurator/runtime_overlay.py`

Implements refcount-based mount/unmount. Key methods:
- `apply(scope_name, contributions) -> TransitionResult` — Atomic apply with rollback.
- `revoke(scope_name) -> TransitionResult` — Atomic revoke.
- `_refcount` dict — Internal per-item refcount across all active scopes.

This is the ground truth for S1–S4 overlap semantics in §7.

### 11.4 Approval Integration

**File:** `[amplifier-module-hooks-approval] amplifier_module_hooks_approval/__init__.py`  
**Config:** `behaviors/modes.yaml` (hooks-approval entry)

The approval hook monitors `session_state.require_approval_tools` and prompts the user
when the mode hook flags a `confirm` tool. The `policy_driven_only: true` configuration
makes the approval hook mode-driven, not static.

### 11.5 Bundle Pre-Activation

**File:** `[amplifier-foundation] amplifier_foundation/bundle/_dataclass.py`

`Bundle.prepare()` walks discovered modes' `contributes` blocks and feeds module sources to
`ModuleActivator`. This ensures cold-start downloads happen at session startup, not on
first mode activation.

### 11.6 CLI Integration

**File:** `[amplifier-app-cli] amplifier_app_cli/main.py`

- `COMMANDS` dict (~line 273) — Built-in command names that override mode shortcuts.
- `_populate_mode_shortcuts()` (~line 327) — Calls `get_shortcuts()`, populates
  `CommandProcessor.MODE_SHORTCUTS`.
- Mode dispatch check (~line 361) — After built-in commands in precedence order.
- `/modes` command — Calls `list_modes(include_unadvertised=False)` by default;
  `--all` flag calls with `True` for operator inspection.

### 11.7 Test Coverage

**Files:**
- `modules/hooks-mode/tests/test_tool_mode.py`
- `modules/hooks-mode/tests/test_events_module.py`

Covers mode discovery, parsing, tool policy enforcement, shortcut registration, and
warn/confirm mechanics. When adding new frontmatter fields, add test coverage here.

---

## Summary Reference Card

```
mode:
  name: <str>                   # Required in practice; defaults to filename stem
  description: <str>            # Shown on activation and in /modes
  shortcut: <str|false>         # Default: name (lowercased). false = disable alias
  advertised: <bool>            # Default: true. false = hidden from LLM listings
  default_action: block|allow   # Default: block
  allowed_transitions: [...]    # Default: absent (any). List = restrict transitions
  allow_clear: <bool>           # Default: true. false = /mode off rejected
  gate_policy: auto|warn|confirm # Optional activation override; absent/null inherits module

  tools:
    safe:    [...]              # Always allowed
    warn:    [...]              # Blocked once with warning; retry proceeds
    confirm: [...]              # Requires user approval per call
    block:   [...]              # Never allowed

  contributes:                  # v1 — lazy-mounted on activation
    agents:
      <name>:
        source: "@bundle:path"
    context:
      - "@bundle:path/file.md"
    skills:
      - "@bundle:path/skill"
    tools: [...]                # v1.1 — deferred
    config: {}                  # v1.1 — deferred
```

**Key invariants:**
- `contributes.agents` non-empty → `delegate` must be reachable via tool policy
- `contributes.skills` non-empty → `load_skill` must be reachable via tool policy
- `mode` and `todo` bypass tool policy (infrastructure tools — always available)
- Refcount semantics: mount at `0→1`, unmount at `1→0`; session baseline holds `+1`
- Activation is atomic with rollback: any failure rolls back all partial mounts/pushes
- `advertised: false` + `contributes.*` = zero LLM token cost until human activates

---

*Authoritative schema reference for `amplifier-bundle-modes` mode system, v1 with v1.1
preview. Contributed by `/mode-design`. Resides at `context/mode-schema-reference.md`.*
