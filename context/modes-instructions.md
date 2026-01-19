# Amplifier Modes

Modes are runtime behavior overlays that modify how you operate without changing the underlying bundle. When a mode is active, you receive mode-specific guidance and tool policies are enforced.

## Commands

| Command | Description |
|---------|-------------|
| `/mode <name>` | Activate a mode (or toggle if already active) |
| `/modes` | List all available modes |
| `/mode off` | Deactivate current mode |

## Built-in Modes

| Mode | Purpose | Behavior |
|------|---------|----------|
| `plan` | Think and discuss, don't implement | Analysis and exploration only - no file modifications |
| `review` | Code review focus | Read-only analysis, critique without changing code |
| `explore` | Codebase exploration | Discovery-oriented, understand before acting |

## How Modes Work

When a mode is active:

1. **Context injection** - The mode's guidance appears as a `<system-reminder source="mode-<name>">` in your context
2. **Tool policies** - Tools are categorized as safe/warn/block per the mode's configuration
3. **Visual indicator** - The user sees `[mode]>` in their prompt

## Tool Policies

Modes can specify how tools should behave:

| Policy | Behavior |
|--------|----------|
| `safe` | Tool works normally |
| `warn` | First call is blocked with a warning; retry to proceed |
| `block` | Tool is disabled entirely |

If a tool isn't listed, `default_action` applies (`block` by default).

**When a tool is blocked or warned:** You'll receive a tool result indicating the mode policy. For `warn` tools, explain what you intend to do and call again if appropriate.

## Custom Modes

Users can create custom modes by adding `.md` files to:
- `.amplifier/modes/` - Project-specific modes
- `~/.amplifier/modes/` - User-global modes

Mode files use YAML frontmatter with a `mode:` section defining name, description, and tool policies, followed by markdown content that gets injected as guidance.

## For You (The Agent)

When you see `<system-reminder source="mode-<name>">` in your context:

1. **You are in that mode** - The user explicitly chose this behavior
2. **Follow the guidance** - The mode's markdown content tells you how to behave
3. **Respect tool policies** - Blocked tools will fail; warned tools need justification
4. **Honor user intent** - The mode reflects what the user wants from this interaction

**Anti-pattern:** Ignoring mode guidance or trying to work around tool restrictions.

**Correct pattern:** Adapt your approach to work within the mode's constraints. If the user needs capabilities the mode restricts, suggest they use `/mode off`.
