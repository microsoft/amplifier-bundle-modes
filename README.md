# amplifier-bundle-modes

A generic mode system for Amplifier that enables runtime behavior modification through user-defined modes.

## Overview

Modes are lightweight runtime overlays that modify assistant behavior without changing the underlying bundle configuration. When a mode is active:

1. **Context injection** - Mode-specific guidance is injected into each turn
2. **Tool moderation** - Tools are allowed, warned, confirmed, or blocked based on mode policy
3. **Visual indicator** - Prompt shows `[mode]>` when active

## Quick Start

```
> /mode plan
Mode: plan — Analyze, strategize, and organize - but don't implement

[plan]> analyze the authentication flow

... assistant explores and discusses without modifying files ...

[plan]> /mode off
Mode off: plan

> now implement the changes
```

## Built-in Modes

| Mode | Description |
|------|-------------|
| `explore` | Zero-footprint codebase exploration |
| `plan` | Analysis and planning without implementation |
| `careful` | Full capability with user confirmation for destructive actions |

See `modes/*.md` for full definitions.

## Tool Policies

Modes control tool access through policies:

| Policy | Behavior |
|--------|----------|
| `safe` | Tool works normally |
| `warn` | Blocked once with warning; retry proceeds |
| `confirm` | Requires user approval via approval hook |
| `block` | Tool disabled entirely |

### Approval Integration

The `confirm` policy integrates with the approval hook system. When a tool is marked `confirm`, the mode hook sets it up for approval, and the approval hook prompts the user before execution.

This is used by `careful` mode for write operations (`write_file`, `edit_file`, `bash`).

## Creating Custom Modes

Create a markdown file with YAML frontmatter:

```markdown
---
mode:
  name: cautious
  description: Ask before any destructive action
  shortcut: cautious   # Optional; defaults to `name`. Use `shortcut: false` to disable.
  
  tools:
    safe:
      - read_file
      - grep
      - glob
    warn:
      - bash
    confirm:
      - write_file
      - edit_file
  
  default_action: block
---

CAUTIOUS MODE: Confirm before any changes.

Before using any tool that modifies state:
1. Explain what you intend to do
2. Wait for user confirmation
3. Then proceed

Do NOT make changes without explicit approval.
```

### Mode File Locations

Modes are discovered from (highest precedence first):

1. `<project>/.amplifier/modes/` - Project-specific modes
2. `~/.amplifier/modes/` - User-defined modes
3. Bundle `modes/` directory - Built-in modes from this bundle
4. Config `search_paths` entries - Explicit additional paths
5. Composed bundle `modes/` directories - Auto-discovered from all bundles in the session

> **Note**: In server/web deployments, "project" is determined by the `session.working_dir` capability, not the server process cwd. This enables correct mode discovery when Amplifier runs as a backend service.

### Known Limitations

> **CLI command name conflicts:** Modes named the same as built-in CLI commands (`help`, `mode`, `modes`, `exit`, `quit`) will have their default `/<name>` slash alias silently overridden by the CLI's built-in command dispatch. These modes remain activatable via `/mode <name>`. To give such a mode a working slash alias, set `shortcut:` explicitly to a non-reserved value.

> **Opt-out syntax note:** `shortcut: false` (YAML boolean, unquoted) disables the alias. `shortcut: "false"` (quoted string) is a shortcut literally named `false` and registers `/false`. Use the unquoted boolean form to disable.

### Third-Party Bundle Modes

Any bundle that includes `hooks-mode` can contribute custom modes by placing `.md` files in a `modes/` directory at the bundle root. These are auto-discovered at runtime — no special configuration needed beyond the directory convention.

> **Naming guidance for third-party bundle authors:** Use descriptive, unique names (e.g. `systems-design` rather than `design`, `perf-audit` rather than `perf`). First-load wins silently on shortcut collision; the second bundle's shortcut is dropped with an INFO log. If two modes claim the same shortcut key, the one discovered first (based on search-path precedence) wins; the other can still be activated via `/mode <name>`.

Example bundle structure:
```
my-bundle/
├── bundle.md
├── modes/
│   ├── my-custom-mode.md    # Automatically discovered
│   └── another-mode.md
└── ...
```

The bundle's `bundle.md` just needs to include `hooks-mode`:
```yaml
hooks:
  - module: hooks-mode
    source: git+https://github.com/microsoft/amplifier-bundle-modes@main#subdirectory=modules/hooks-mode
```

All modes from all composed bundles appear in `/modes` and are activatable via `/mode <name>` or shortcuts.

### Mode Configuration

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Mode identifier |
| `description` | No | Shown when mode activates |
| `shortcut` | No (defaults to `name`) | Slash-command alias. Defaults to the mode's `name` (lowercased). Set to `false` to disable. Must match `^[a-z][a-z0-9_-]*$` after lowercasing; invalid values log a warning and register no alias. |
| `tools.safe` | No | Tools always allowed |
| `tools.warn` | No | Tools that warn once, then allow |
| `tools.confirm` | No | Tools that require user approval |
| `tools.block` | No | Tools explicitly blocked |
| `default_action` | No | `block` (default) or `allow` for unlisted tools |

## Commands

| Command | Action |
|---------|--------|
| `/mode <name>` | Toggle mode on/off |
| `/mode <name> on` | Explicit activate |
| `/mode <name> off` | Explicit deactivate |
| `/mode off` | Clear any active mode |
| `/modes` | List available modes |
| `/<mode-name>` | Auto-generated shortcut for each mode (use `shortcut: false` to disable, or set `shortcut:` to override) |

## Architecture

```
amplifier-bundle-modes/
├── bundle.md                    # Thin bundle wrapper
├── behaviors/
│   └── modes.yaml               # Hooks configuration
├── modes/                       # Built-in mode definitions
│   ├── explore.md
│   ├── plan.md
│   └── careful.md
├── modules/
│   └── hooks-mode/              # Generic mode hook module
│       ├── pyproject.toml
│       └── amplifier_module_hooks_mode/
│           └── __init__.py
├── context/
│   └── modes-instructions.md    # Agent-facing context
└── README.md
```

## How It Works

1. **Mode Discovery**: `ModeDiscovery` searches paths for `.md` files
2. **Mode Loading**: `parse_mode_file()` extracts YAML config + markdown context
3. **Context Injection**: `provider:request` hook injects mode's markdown as `<system-reminder>`
4. **Tool Moderation**: `tool:pre` hook checks each tool against mode's policy
5. **Approval Integration**: `confirm` tools are delegated to approval hook via `require_approval_tools`

## Integration

Include in your bundle:

```yaml
includes:
  - bundle: foundation
  - bundle: modes
```

The mode system hooks will automatically register and begin discovering modes.

## Philosophy

Modes embody Amplifier's "mechanism not policy" principle:

- **Bundle provides mechanism** - Generic hooks, discovery, moderation
- **Mode files provide policy** - Tool lists, context, behavior
- **App provides toggle** - `/mode` command, prompt indicator
- **Users customize freely** - Create modes without writing code

## License

MIT

## Contributing

> [!NOTE]
> This project is not currently accepting external contributions, but we're actively working toward opening this up. We value community input and look forward to collaborating in the future. For now, feel free to fork and experiment!

Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
