---
name: mode-design-discipline
description: >
  Authoring discipline for Amplifier modes. Covers anti-bloat patterns,
  naming hygiene, when advertised:false is right, how the body must narrate
  contributions, and how to test the four overlap scenarios (S1–S4) before
  committing a mode.
---

# Mode Design Discipline

This skill captures the judgment calls that separate well-crafted modes from ones that
confuse the LLM, bloat context, or break silently on deactivation.

---

## 1. Most Modes Don't Need Contributions — And Most Behaviors Shouldn't Have Heavy `context.include` Either

This rule has a sibling that lives one layer up in the bundle structure. The discipline
described in this section is half the picture; the other half is:

> **Most bundle behaviors should NOT have heavy entries in their `context.include` list.**

A behavior YAML's `context.include` lands in the always-on system prompt for every session
that composes the behavior. The reflex to "just include the methodology file so it's always
available" creates exactly the same bloat as the contributions reflex in modes — different
mechanism, same pathology.

The bar is symmetric:

- **Mode `contributes`**: only add when the item is specialist-domain and only relevant
  during the mode's workflow. Otherwise put it in the bundle (always-on) or skill (on-demand).
- **Behavior `context.include`**: only add when the file is a lightweight awareness pointer
  (<500 tokens, universally relevant). Otherwise put it in an agent body (context-sink),
  a mode (mode-gated), or a skill (on-demand).

See `amplifier-foundation/docs/BUNDLE_GUIDE.md §"Behavior context.include Policy"` and
`AGENT_AUTHORING.md §"Anti-Pattern: Heavy Context in Behaviors"` for the policy authoring
behaviors must follow.

The two rules combine to form a single discipline: **never put heavy content in the
always-on layer when an on-demand mechanism (agent body, mode contribution, skill) can hold
it.** The mode-design path and the behavior-design path are both governed by it.

---

The single biggest anti-bloat smell within modes: adding `contributes:` to every mode because
the schema supports it.

### Smell test — "This should be in the bundle, not the mode"

- The agent is used in **every** session, not just when this mode is active.
- The context file is a short reminder (< 200 tokens) that always helps.
- The skill is broadly applicable and used across many workflows.
- The author just wants the item "grouped here" for organisational reasons.

**Fix:** Put it in `bundle.md`'s includes. Mode activation overhead is zero — the item
is always mounted.

### Smell test — "This belongs in the mode"

- The agent is a specialist that only makes sense **during** this mode's workflow
  (e.g. a `security-guardian` agent in a `security-audit` mode).
- The context file is a large reference document (> 1 000 tokens) that would burn
  per-turn budget when inactive.
- The skill covers domain knowledge that is irrelevant outside the mode.
- The item's presence in the LLM's awareness while the mode is **inactive** would
  cause confusion or unexpected behaviour.

**Rule:** If activating the mode makes the item useful and deactivating makes it
irrelevant, it belongs in `contributes`. Otherwise it belongs in `bundle.md`.

---

## 2. Tool Policy Minimalism

### Default: block + a small explicit safe list

The canonical starting point for a restrictive mode:

```yaml
tools:
  safe:
    - read_file
    - glob
    - grep
    - web_search
    - web_fetch
    - load_skill
    - LSP
    - todo
  default_action: block
```

**Rule of thumb:** Start with this list. Add tools one at a time only when the primary
task genuinely requires them. Each addition is a policy decision — own it.

### When to use each bucket

| Bucket | When |
|--------|------|
| `safe` | Tools the LLM needs for the primary task without friction |
| `warn` | Tools allowed but risky — the one-call warning creates intentionality |
| `confirm` | Truly irreversible, high-impact operations (destructive bash, mass deletes) |
| `block` | Tools that must **never** execute in this mode |

**Avoid `confirm` for read operations.** Confirming `read_file` or `grep` causes approval
fatigue. Reserve `confirm` for ops that cannot be undone.

### Contributions require matching tool access

| Contribution | Required tool in policy |
|--------------|------------------------|
| `contributes.agents` non-empty | `delegate` in `safe` or `warn` |
| `contributes.skills` non-empty | `load_skill` in `safe` or `warn` |

The parse-time linter warns on violation but does not block loading — the mode will
fail at runtime.

---

## 3. Naming Hygiene

### Good mode names

```
systems-design     # Descriptive, namespaced
security-audit     # Action + domain
plan               # Short canonical verb (built-in — OK for core bundle)
code-review        # Hyphenated compound noun
perf-audit         # Abbreviated only when unambiguous
```

### Bad mode names

```
design             # Too generic — collides with other bundles
audit              # Ambiguous — security? code? performance?
mymode             # No semantics
work               # Not descriptive
sd                 # Opaque abbreviation
```

### Shortcut conventions

- Default: omit `shortcut:` — the runtime registers `/<name>` automatically.
- Override: `shortcut: sdr` when the default would be too long or collide.
- Disable: `shortcut: false` (unquoted YAML boolean) to require `/mode <name>`.
- **Never** `shortcut: "false"` (quoted) — that registers a shortcut named `/false`.

### Third-party bundle rules

Bundle-shipped modes must use descriptive, unique names. Generic names like `design` or
`perf` will silently lose their shortcut if any other bundle or user mode loads first.
Prefer `<domain>-<action>` patterns: `ui-design`, `perf-audit`, `security-review`.

---

## 4. When `advertised: false` Is Right

`advertised: false` hides a mode from the LLM's `/modes` listing. The human can still
activate it via `/mode <name>` or see it in `/modes --all`.

### Right reasons to use `advertised: false`

- **Rare specialist workflows** that would clutter the LLM's mode awareness for 95% of
  sessions (e.g. `mode-design` itself — relevant only when authoring modes).
- **Heavy context contributions** that should be zero-cost until a human explicitly
  requests them. The `advertised: false` + `contributes.context` pattern is the canonical
  token-savings story.
- **Operator tooling** modes designed for administrators, not end users.
- **Prerequisite modes** that are sub-steps in a multi-mode workflow and should not
  appear as top-level choices.

### Wrong reasons to use `advertised: false`

| Temptation | Why it's wrong |
|------------|----------------|
| Hiding WIP | A broken mode in the bundle will load and cause confusion regardless of `advertised`. Fix or remove it. |
| Deceiving the LLM | The LLM cannot be prevented from acting on a mode that IS active. Hiding it from listings doesn't change its behaviour when active. |
| Hiding mistakes | If the mode restricts default behaviour, hiding it from the LLM makes the assistant appear broken. Users cannot understand why tools are blocked. |
| Reducing clutter during development | Use a feature branch. `advertised: false` is a permanent production setting, not a dev flag. |

**Key rule:** `advertised: false` is appropriate for **additive** specialist capabilities.
It is **wrong** for modes that restrict default behaviour — those must be visible so users
understand why the assistant behaves differently.

### Advertising rule for cross-doc references

If any agent-readable file (bundle context, agent body, recipe input, README, or `.md`
contributed by another mode) mentions a mode by name, that mode **must** be advertised.
Documenting an invisible capability is worse than not documenting it — the LLM sees the
name, infers the capability exists, tries to invoke it, and either fails silently or
hallucinates plausible behaviour.

Equivalently: an `advertised: false` mode **must not** appear by name in any agent-readable
documentation. Activation of unadvertised modes must happen out-of-band — user invocation,
hook-driven activation, recipe step, or a programmatic `mode(set, name=…)` call from a
known agent with a hard-coded mode name. The agent-facing surface should know nothing of
these modes.

This rule has a corollary for migration work: when moving heavy context from always-on
into a mode, if the always-on awareness file will name the mode (to tell the agent "if
you're doing X, activate `/mode foo`"), that mode **must** be advertised. Otherwise the
breadcrumb misleads.

A quick mechanical check: `grep -rn '`/mode <name>`' <repo>` across the bundle's
context/, agents/, and docs/ directories. Any hit on an unadvertised mode is a violation.

---

## 5. The Body Must Narrate Contributions

When a mode uses `contributes:`, the body **must** tell the LLM about the contributed
items. The runtime mounts them silently; the body is the only mechanism for informing the
LLM they are available.

### Required body sections when contributing

**Contributing agents:**

```markdown
## Specialist Agents (available via `delegate`)

- `security-guardian` — systematic vulnerability review
- `dep-scanner` — dependency CVE analysis

Use `delegate(agent="security-guardian", ...)` for deep security analysis.
```

**Contributing skills:**

```markdown
## Loaded Skills

- `owasp-patterns` — OWASP Top 10 patterns and remediation guidance

These skills are automatically available via `load_skill`. Load them when
beginning a review: `load_skill(skill_name="owasp-patterns")`
```

**Contributing context:**

```markdown
## Reference Material (auto-injected)

`owasp-checklist.md` — OWASP Top 10 checklist for systematic review.
This document is in your context. Use it as the primary review framework.
```

### Cross-Mode Transition Narration

Workflow modes that participate in a pipeline (e.g. `/brainstorm` → `/write-plan` →
`/execute-plan`) need a way for the routing LLM to discover the next-step mode while
the current mode is active. The canonical pattern is **mode body narration**, not
schema features.

Naming an adjacent mode in your mode body is FREE: the body is injected only when this
mode is active, so the mention of the next mode is itself gated by activation. This
respects the advertising rule for unadvertised modes — you can name them in a body
because the body's audience is the same audience that has the mode active.

Recommended body section:

```markdown
## Transitions

**Done when:** [explicit completion criterion for this mode's work]

**Golden path:** `/<next-mode>`
- Tell user: "[short explanation of why next-mode is appropriate]"
- Use `mode(operation='set', name='<next-mode>')` to transition.

**Dynamic transitions:**
- If [condition A] → use `mode(operation='set', name='<other-mode-1>')` because [reason]
- If [condition B] → use `mode(operation='set', name='<other-mode-2>')` because [reason]
- If [condition C] → stay in this mode because [reason]
```

The superpowers workflow modes (`brainstorm`, `write-plan`, `execute-plan`, `debug`,
`verify`, `finish`) and the parallax-discovery wave modes (`discovery`, `verification`,
`adversarial`, `synthesis`) all use this pattern. Read those for worked examples.

**Combine with `allowed_transitions:`** when you want both the LLM-facing prose and
the framework-level guard. The body narrates, the field enforces. They are
complementary — don't pick one. The frontmatter prevents the LLM from transitioning
to modes outside the workflow (defense at the schema layer); the body tells the LLM
which transitions are appropriate and why (guidance at the prompt layer).

For unadvertised modes that participate in a workflow: this body-narration pattern
is the right discovery mechanism. `mode(operation="list")` filters by `advertised:`
and will NOT surface unadvertised modes — so the routing LLM relies entirely on the
parent mode's body to know that the next step exists. If you want cross-mode
discovery without schema changes, this is the answer. (No `reveals:` schema field
exists; if one is ever added, this pattern stays valid for the simple case.)

### Companion Skill: Mandatory First-Action Loading

Many modes pair with a "companion skill" that contains the methodology and discipline
for the workflow. The skill is contributed by the mode (`contributes.skills`) so it's
discoverable via `load_skill` only while the mode is active.

**Problem:** the framework doesn't auto-load skills on mode activation. The LLM has
to call `load_skill(skill_name="<companion>")` itself. If it doesn't, the mode's
methodology never gets into context and the agent operates with generic instincts
instead of the structured workflow the mode is designed to enforce.

**Convention:** the mode body opens with a `<MANDATORY>` block instructing the LLM
to load the skill BEFORE responding to the user's first request in the mode.

Example (taken from systems-design):

```markdown
<MANDATORY>
## First Action: Load the Companion Skill

**Your VERY FIRST action when this mode activates MUST be:**

```
load_skill(skill_name="<companion-skill-name>")
```

This is not optional. This is not "if you think it's helpful." This is a hard
requirement. The companion skill contains the [phase-by-phase workflow | step-by-step
methodology | discipline framework] that governs your behavior in this mode. Without
it, you will produce generic [responses | output | analysis] instead of the
structured work this mode is designed to produce.

**Do NOT respond to the user's question before loading the skill.** The skill
determines HOW you respond. Load it first, then follow it.

**Common rationalization to reject:** "This is just a quick question, I don't need
the methodology." WRONG. If the user activated this mode, they want the structured
work, not a conversational answer. If they wanted a quick take, they wouldn't have
activated a mode.
</MANDATORY>
```

This is a workaround for a missing framework feature — the schema does NOT yet
support `on_activation_load_skills: [list]`. Until/unless that field is added, the
MANDATORY narration is the only mechanism. It relies on LLM compliance with the
imperative language; it is not framework-enforced.

**Anti-pattern:** assuming the LLM will discover the companion skill via the
skills-visibility hook listing. The hook surfaces skill names+descriptions but does
not load skill bodies; the LLM still has to call `load_skill()`. Bodies need the
MANDATORY block to make this reliable.

If your mode has a single companion skill that should ALWAYS load on activation,
use this pattern verbatim. Treat any variation as a yellow flag — the convention's
imperative tone is what makes the LLM actually comply.

### Example body fragment

```markdown
---

SECURITY AUDIT MODE: Systematic read-only security review.

## Available Specialist Agents

- `security-guardian` (via `delegate`) — OWASP-aligned code review
- `dep-scanner` (via `delegate`) — dependency CVE scanner

## Reference Material (auto-injected)

`owasp-checklist.md` is in your context. Use it to structure findings.

## Loaded Skills

Load `security-review-patterns` with `load_skill` before beginning a deep review.

## Workflow
1. Survey attack surface with read tools
2. Delegate specific checks to `security-guardian`
3. Compile findings in `SECURITY-FINDINGS.md`
4. Use /mode off when complete; implement fixes in a separate session
```

**Anti-pattern:** A `contributes.agents` block with no mention of those agents in the body.
The LLM will not know to use them and will proceed without the specialist capability.

---

## 6. Test the Four Overlap Scenarios (S1–S4)

Before committing a mode with `contributes:`, verify all four overlap scenarios manually.
These cover every way a contributed item can relate to the session baseline and other
active modes.

### S1 — Item in session baseline AND in mode

**Scenario:** The contributed item is also declared in `bundle.md`.

**Expected:** Mode activation has no effect on the item (it's already mounted, refcount
goes from 1 to 2). Mode deactivation does not unmount it (refcount returns to 1).

**Verification:**
1. Start a session. Confirm the item is available (e.g. agent appears in `delegate` list).
2. Activate the mode. Confirm the item is still available (no change).
3. Deactivate the mode. Confirm the item is still available (not removed).

---

### S2 — Item only in mode (not in session baseline)

**Scenario:** The contributed item does NOT appear in `bundle.md`. This is the most
common contribution use case.

**Expected:** Item is absent before activation, present while active, absent after
deactivation.

**Verification (activate-assert-deactivate-assert-gone test):**
1. Start a session. Confirm the item is **NOT** available (e.g. agent not in `delegate`
   list, skill not discoverable, context file not injected).
2. Activate the mode (`/mode <name>`).
3. Assert the item IS now available.
4. Deactivate the mode (`/mode off`).
5. Assert the item is **gone** — not present in the delegate list, not loadable, not
   in context.

This test must pass for every item listed in `contributes.*`. A failure in step 5 (item
persists after deactivation) indicates a refcount leak.

---

### S3 — Item in Mode M1 AND Mode M2, not in session baseline

**Scenario:** Two modes share a contribution. M1 is active, then switched to M2.

**Expected:** Item is mounted when M1 activates (refcount 0→1), unmounted when M1
deactivates (1→0), then re-mounted when M2 activates (0→1). Brief unavailability during
the transition is a known v1 limitation.

**Verification:**
1. Activate M1. Confirm item is available.
2. Activate M2 (switching from M1). Confirm item is available after the transition.
3. Deactivate M2. Confirm item is gone.
4. Confirm no orphaned mounts remain.

---

### S4 — Item in session baseline AND in both M1 and M2

**Scenario:** The item is in `bundle.md` and both modes' `contributes`.

**Expected:** Item is always mounted; zero churn. Refcount goes 1→2→3→2→1, never hitting
0. Mode activations and deactivations are all no-ops for this item.

**Verification:**
1. Start session. Confirm item is available (baseline, refcount 1).
2. Activate M1. Confirm item still available (refcount 2).
3. Activate M2. Confirm item still available (refcount 3).
4. Deactivate M1. Confirm item still available (refcount 2).
5. Deactivate M2. Confirm item still available (refcount 1, baseline).
6. End session (or remove baseline). Confirm item is gone (refcount 0).

---

## 7. Anti-Patterns

### Treating the mode body as a system prompt

The mode body is injected as a `<system-reminder source="mode-<name>">` per turn while
the mode is active. It is NOT a persistent system prompt replacement. Do not put
instructions that assume global context — be explicit each time.

### Putting schema reference in the body

Large schema tables in the mode body = thousands of tokens of system-reminder overhead
per turn. Put heavy reference material in `contributes.context` (injected via context
pipeline, not repeated as system reminder) or expose it as a skill loaded on demand.

### Modes blocking their own contributions

```yaml
tools:
  default_action: block
# contributes.agents is non-empty but delegate is NOT in tools.safe
```

The mode mounts agents but the LLM cannot call them. The parse-time linter warns but
the error only surfaces at runtime. Always run the authoring checklist after any change
to `contributes.*`.

### Modes depending on session state

Mode body instructions should not assume the LLM has seen earlier turns. The system-
reminder is injected fresh every turn. Write the body as if it's the LLM's first
introduction to the mode — state the intent, available tools, and workflow explicitly.

---

## 8. Workflow When Designing a New Mode

1. **State the purpose in one sentence.** If you can't, the mode isn't ready to design.
2. **List the LLM's primary actions** during the mode. Each action implies a tool —
   map actions to tools before writing any YAML.
3. **Apply the safe-list rule.** Start with the minimal read-only tools. Add write tools
   only if explicitly required by a primary action.
4. **Decide on contributions.** Apply the smell tests from §1. If items belong in the
   bundle, don't add them to `contributes`.
5. **Choose `advertised` setting.** Apply the criteria from §4. Default is `true`.
6. **Write the body.** Lead with intent. If contributing agents/skills/context, narrate
   them per §5. End with an exit hint (`/mode off` or next transition).
7. **Run the authoring checklist** (see `context/mode-schema-reference.md §8`).
8. **Test S1–S4** per §6 for any mode with `contributes:`. For modes without
   contributions, run the final verification checklist (§8.6 of schema reference).

---

## 9. Reading Order for New Authors

1. `context/modes-instructions.md` — How modes work at runtime (the LLM's perspective).
2. `context/mode-schema-reference.md` §1–4 — File location, naming, frontmatter fields,
   tool policy.
3. `context/mode-schema-reference.md §5` — The `contributes` block and referential
   integrity rules.
4. `context/mode-schema-reference.md §7` — Refcount semantics and overlap scenarios.
5. This skill (mode-design-discipline) — Judgment calls and discipline.
6. `context/mode-schema-reference.md §8` — Authoring checklist (use before every commit).
7. `context/mode-schema-reference.md §9–10` — Common patterns and anti-patterns.

Start with an existing mode (`modes/plan.md` or `modes/explore.md`) as a template before
writing from scratch.
