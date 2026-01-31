# Amplifier Modes

Modes are runtime behavior overlays that modify how you operate without changing the underlying bundle. When a mode is active, you receive mode-specific guidance and tool policies are enforced.

## Commands

| Command | Description |
|---------|-------------|
| `/mode <name>` | Activate a mode (or toggle if already active) |
| `/modes` | List all available modes |
| `/mode off` | Deactivate current mode |

**Important:** When you see these commands, you MUST use the `mode` tool to actually activate/deactivate modes. Simply understanding the mode isn't enough - tool policies are only enforced when `mode(action="activate", mode="<name>")` is called.

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

## For You (The Agent)

When you see `<system-reminder source="mode-<name>">` in your context:

1. **You are in that mode** - The user explicitly chose this behavior
2. **Follow the guidance** - The mode's markdown content tells you how to behave
3. **Respect tool policies** - Blocked tools will fail; warned tools need justification; confirmed tools need user approval
4. **Honor user intent** - The mode reflects what the user wants from this interaction

**Anti-pattern:** Ignoring mode guidance or trying to work around tool restrictions.

**Correct pattern:** Adapt your approach to work within the mode's constraints. If the user needs capabilities the mode restricts, suggest they use `/mode off`.

## Cross-Bundle Mode Discovery

Modes can come from multiple sources:
1. Built-in modes in the modes bundle (`@modes:modes/`)
2. Modes from other loaded bundles (check `~/.amplifier/settings.yaml` for `bundle.added` paths, then look in their `modes/` directories)
3. Custom project modes (`.amplifier/modes/`)
4. Custom user modes (`~/.amplifier/modes/`)

**When listing modes with `/modes`:** Check ALL these locations to find all available modes. Read the settings.yaml to discover which bundles are loaded, then check each bundle's `modes/` directory for additional mode files.
