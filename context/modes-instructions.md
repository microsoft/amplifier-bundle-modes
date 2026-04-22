# Amplifier Modes

Modes are runtime behavior overlays that modify how you operate without changing the underlying bundle. When a mode is active, you receive mode-specific guidance and tool policies are enforced.

## Commands

| Command | Description |
|---------|-------------|
| `/mode <name>` | Activate a mode (or toggle if already active) |
| `/modes` | List all available modes |
| `/mode off` | Deactivate current mode |

## How Modes Work

When a mode is active:

1. **Context injection** - The mode's guidance appears as a `<system-reminder source="mode-<name>">` in your context
2. **Tool policies** - Tools are categorized per the mode's configuration
3. **Visual indicator** - The user sees `[mode]>` in their prompt

## Tool Policies

Modes specify how tools should behave:

| Policy | Behavior |
|--------|----------|
| `safe` | Tool works normally |
| `warn` | First call is blocked with a warning; retry to proceed |
| `confirm` | Requires user approval before execution |
| `block` | Tool is disabled entirely |

If a tool isn't listed, `default_action` applies (`block` by default).

**When a tool is blocked or warned:** You'll receive a tool result indicating the mode policy. For `warn` tools, explain what you intend to do and call again if appropriate.

**When a tool requires confirmation:** The approval system will prompt the user. Wait for their decision before proceeding.

## Custom Modes

Users can create custom modes by adding `.md` files to:
- `.amplifier/modes/` - Project-specific modes
- `~/.amplifier/modes/` - User-global modes

Mode files use YAML frontmatter with a `mode:` section defining name, description, and tool policies, followed by markdown content that gets injected as guidance.

### Mode Configuration

Every mode file has this structure:

```yaml
---
mode:
  name: my-mode             # Required in practice; defaults to filename stem if omitted
  description: "What this mode does"
  shortcut: my-mode         # Optional; defaults to the mode's name (lowercased) when omitted
  tools:
    safe: [read_file, grep] # Always allowed
    warn: [bash]            # Allowed after first warning
    confirm: [write_file]   # Requires user approval
    block: [delete_file]    # Never allowed
  default_action: block     # What to do with unlisted tools: "block" or "allow"
---

Markdown guidance injected as context when the mode is active.
```

**Field reference:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Recommended | The mode's identifier. Defaults to the filename stem if omitted. |
| `description` | No | Human-readable description shown in `/modes` output. |
| `shortcut` | No (defaults to `name`) | Slash-command alias. When omitted, defaults to the mode's `name` (lowercased), registering `/<name>` automatically. Set `shortcut: false` to disable the alias entirely. Must match `^[a-z][a-z0-9_-]*$` after lowercasing; invalid values log a warning and register no alias. |
| `tools.safe` | No | Tools always allowed. |
| `tools.warn` | No | Tools allowed after a one-time warning. |
| `tools.confirm` | No | Tools requiring user approval. |
| `tools.block` | No | Tools never allowed. |
| `default_action` | No | Policy for unlisted tools: `"block"` (default) or `"allow"`. |

**Shortcut field details:**

- **Default behavior:** If `shortcut:` is omitted, the mode registers `/<name>` automatically (lowercased). For example, a mode with `name: systems-design` gets `/systems-design` for free.
- **Opt-out:** Set `shortcut: false` (YAML boolean, unquoted) to disable the alias. The mode remains activatable via `/mode <name>`.
- **Explicit shortcut:** Set `shortcut: sdr` to register `/sdr` instead of `/<name>`.
- **YAML distinction:** `shortcut: false` (YAML boolean) is opt-out. `shortcut: "false"` (quoted string) is a shortcut literally named `false` and will register `/false`.

**Known limitations:**

Modes whose `name` matches a built-in CLI command (`help`, `mode`, `modes`, `exit`, `quit`) will register a default `/<name>` alias that is silently overridden by the CLI's built-in command dispatch. These modes remain activatable via `/mode <name>`. To give such a mode a working slash alias, set `shortcut:` explicitly to a non-reserved value (e.g., `shortcut: my-help`).

**Third-party bundle naming guidance:**

Bundle-shipped modes should use descriptive, unique names (e.g. `systems-design` rather than `design`, `perf-audit` rather than `perf`). First-load wins silently on shortcut collision; the second bundle's shortcut is dropped with an INFO log in `get_shortcuts()`.

## For You (The Agent)

When you see `<system-reminder source="mode-<name>">` in your context:

1. **You are in that mode** - The user explicitly chose this behavior
2. **Follow the guidance** - The mode's markdown content tells you how to behave
3. **Respect tool policies** - Blocked tools will fail; warned tools need justification; confirmed tools need user approval
4. **Honor user intent** - The mode reflects what the user wants from this interaction

**Anti-pattern:** Ignoring mode guidance or trying to work around tool restrictions.

**Correct pattern:** Adapt your approach to work within the mode's constraints. If the user needs capabilities the mode restricts, suggest they use `/mode off`.

## Mode Tool (Agent-Initiated Transitions)

When the `mode` tool is available, agents can request mode changes programmatically:

| Operation | Description |
|-----------|-------------|
| `mode(operation="list")` | List available modes |
| `mode(operation="current")` | Check active mode |
| `mode(operation="set", name="plan")` | Request mode activation |
| `mode(operation="clear")` | Deactivate current mode |

The default gate policy is `warn` — the first request is blocked with a reminder. Call again to confirm the transition. This prevents accidental mode changes while still allowing agent-driven workflows.
