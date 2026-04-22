---
bundle:
  name: modes
  version: 1.1.0
  description: Generic mode system for runtime behavior modification

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: modes:behaviors/modes
---

# Modes Bundle

@modes:context/modes-instructions.md

---

Provides a generic mode system for Amplifier. Modes are runtime behavior overlays that modify how the assistant operates.

## Usage

```
/mode plan       # Enable plan mode
/mode careful    # Switch to careful mode
/mode off        # Disable current mode
/modes           # List available modes
```

## Built-in Modes

- **plan** - Think and discuss, don't implement
- **careful** - Full capability with user confirmation for destructive actions
- **explore** - Pure exploration, understand before acting

## Creating Custom Modes

Create a `.md` file in `.amplifier/modes/` or `~/.amplifier/modes/`:

```markdown
---
mode:
  name: mymode
  description: My custom mode
  shortcut: mymode   # Optional; defaults to `name`. Use `shortcut: false` to disable.
  
  tools:
    safe: [read_file, grep]
    warn: [bash]
  
  default_action: block
---

MODE CONTEXT: Instructions injected when mode is active...
```
