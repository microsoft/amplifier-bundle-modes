---
bundle:
  name: modes
  version: 1.0.0
  description: Generic mode system for runtime behavior modification

includes:
  - bundle: modes:behaviors/modes
---

# Modes Bundle

Provides a generic mode system for Amplifier. Modes are runtime behavior overlays that modify how the assistant operates.

## Usage

```
/mode plan       # Enable plan mode
/mode review     # Switch to review mode  
/mode off        # Disable current mode
/modes           # List available modes
```

## Built-in Modes

- **plan** - Think and discuss, don't implement
- **review** - Analyze and critique code without modifying
- **explore** - Pure exploration, understand before acting

## Creating Custom Modes

Create a `.md` file in `.amplifier/modes/` or `~/.amplifier/modes/`:

```markdown
---
mode:
  name: mymode
  description: My custom mode
  shortcut: mymode
  
  tools:
    safe: [read_file, grep]
    warn: [bash]
  
  default_action: block
---

MODE CONTEXT: Instructions injected when mode is active...
```
