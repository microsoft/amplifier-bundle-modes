# amplifier-bundle-modes

A generic mode system for Amplifier that enables runtime behavior modification through user-defined modes.

## Overview

Modes are lightweight runtime overlays that modify assistant behavior without changing the underlying bundle configuration. When a mode is active:

1. **Context injection** - Mode-specific guidance is injected into each turn
2. **Tool moderation** - Tools are allowed, warned, or blocked based on mode policy
3. **Visual indicator** - Prompt shows `[mode]>` when active

## Quick Start

```
> /mode plan
Mode: plan — Think and discuss, don't implement

[plan]> analyze the authentication flow

... assistant explores and discusses without modifying files ...

[plan]> /mode off
Mode off: plan

> now implement the changes
```

## Built-in Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `plan` | Think and discuss, don't implement | Complex tasks requiring analysis first |
| `review` | Analyze and critique without modifying | Code review sessions |
| `explore` | Pure exploration, understand before acting | Learning a new codebase |

## Creating Custom Modes

Create a markdown file with YAML frontmatter:

```markdown
---
mode:
  name: cautious
  description: Ask before any destructive action
  shortcut: cautious
  
  tools:
    safe:
      - read_file
      - grep
      - glob
    warn:
      - bash
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

1. `.amplifier/modes/` - Project-specific modes
2. `~/.amplifier/modes/` - User-defined modes
3. Bundle `modes/` directory - Built-in modes

### Mode Configuration

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Mode identifier |
| `description` | No | Shown when mode activates |
| `shortcut` | No | Creates `/shortcut` alias command |
| `tools.safe` | No | Tools always allowed |
| `tools.warn` | No | Tools that warn once, then allow |
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
| `/plan`, `/review` | Shortcuts (if defined) |

## Architecture

```
amplifier-bundle-modes/
├── bundle.md                    # Thin bundle wrapper
├── behaviors/
│   └── modes.yaml               # Hooks configuration
├── modes/                       # Built-in mode definitions
│   ├── plan.md
│   ├── review.md
│   └── explore.md
├── modules/
│   └── hooks-mode/              # Generic mode hook module
│       ├── pyproject.toml
│       └── hooks_mode/
│           └── __init__.py
└── README.md
```

## How It Works

1. **Mode Discovery**: `ModeDiscovery` searches paths for `.md` files
2. **Mode Loading**: `parse_mode_file()` extracts YAML config + markdown context
3. **Context Injection**: `prompt:submit` hook injects mode's markdown as `<system-reminder>`
4. **Tool Moderation**: `tool:pre` hook checks each tool against mode's policy

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
