# Mode Tool Module

Provides a tool for agents to activate and deactivate modes.

## Usage

When mounted, this module provides a `mode` tool that agents can use to:

- **activate**: Activate a mode by name
- **deactivate**: Turn off the current mode
- **list**: List all available modes
- **current**: Get the currently active mode

## Example

```json
{"action": "activate", "mode": "plan"}
{"action": "deactivate"}
{"action": "list"}
{"action": "current"}
```

## Requirements

This module requires `hooks-mode` to be loaded first, as it relies on:
- `session_state["mode_discovery"]` for finding modes
- `session_state["mode_hooks"]` for resetting warnings on mode switch
