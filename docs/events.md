# Mode Events

The `amplifier-bundle-modes` bundle emits 8 named events on the kernel's hook bus
covering mode lifecycle transitions and per-tool policy enforcement. Both
modules in the bundle independently contribute their event catalogues to the
`observability.events` discovery channel, so consumers can subscribe to mode
events without hard-coding event names.

## Purpose

The event surface enables:

- **Logging and tracing** — record every mode transition and gated activation.
- **Observability dashboards** — count tool blocks/warnings by mode, monitor
  context injection cadence.
- **Custom reaction hooks** — react to mode changes in other modules
  (e.g. update UI badges, swap tool prompts).
- **Audit trails** — verify that policy gates fired before sensitive mode
  activations.

All emissions are fire-and-forget. Emission failures cannot break mode
enforcement: every `coordinator.hooks.emit(...)` call is wrapped in
`try / except Exception` with a `logger.warning(...)` log.

## Event Catalogue

### `mode:activated`

- **Owner:** `tool-mode`
- **When:** Mode is set from off → on (gate policy passed).
- **Payload:**
  ```python
  {
      "mode": str,
      "description": str,
      "default_action": str,        # "block" | "allow"
      "safe_tools": list[str],
      "warn_tools": list[str],
      "confirm_tools": list[str],
      "block_tools": list[str],
  }
  ```
- **Not emitted when:** Transitioning from one active mode to another —
  `mode:changed` fires instead. The two events are mutually exclusive.

### `mode:changed`

- **Owner:** `tool-mode`
- **When:** Active mode changes from mode A to mode B (gate policy passed).
- **Payload:**
  ```python
  {
      "from_mode": str,
      "to_mode": str,
      "description": str,           # description of the new (to_mode) mode
      "default_action": str,
      "safe_tools": list[str],
      "warn_tools": list[str],
      "confirm_tools": list[str],
      "block_tools": list[str],
  }
  ```
- **Not emitted when:** Activating from off → on — `mode:activated` fires
  instead.

### `mode:cleared`

- **Owner:** `tool-mode`
- **When:** Active mode is deactivated via `mode(clear)`.
- **Payload:**
  ```python
  {"previous_mode": str}
  ```
- **Not emitted when:** `mode(clear)` is called while no mode is active —
  there is nothing to clear.

### `mode:transition_denied`

- **Owner:** `tool-mode`
- **When:** A `mode(set, X)` call is rejected because mode X is not in the
  current mode's `allowed_transitions` list.
- **Payload:**
  ```python
  {
      "from_mode": str,
      "to_mode": str,
      "allowed_transitions": list[str],
  }
  ```
- **Not emitted when:** Gate policy denials (use `mode:activation_gated`),
  unknown mode names, or successful transitions.

### `mode:activation_gated`

- **Owner:** `tool-mode`
- **When:** Gate policy (`warn` or `confirm`) holds back an activation
  pending user consent. Fires for both off → on and on → on attempts.
- **Payload:**
  ```python
  {
      "gate_policy": str,           # "warn" | "confirm"
      "target_mode": str,
      "description": str,
      "from_mode": str | None,      # None when transitioning from off
  }
  ```
- **Not emitted when:** Gate policy is `auto` (no user consent gate),
  or on the second `warn` retry that proceeds to activation.

### `mode:tool_blocked`

- **Owner:** `hooks-mode`
- **When:** A tool call is denied by the active mode's policy.
- **Payload:**
  ```python
  {
      "tool_name": str,
      "mode": str,
      "reason": str,                # "block_list" | "default_action"
  }
  ```
- **Not emitted when:** The tool is allowed (safe list, infrastructure
  bypass, confirm list pass-through, warn-list retry, or
  `default_action="allow"`).

### `mode:tool_warned`

- **Owner:** `hooks-mode`
- **When:** A warn-listed tool is denied with a one-time warning. Fires
  exactly once per (mode, tool) pair until `reset_warnings()` is called
  (which happens on every mode activation/clear).
- **Payload:**
  ```python
  {
      "tool_name": str,
      "mode": str,
  }
  ```
- **Not emitted when:** The same warn-listed tool is called a second time
  in the same mode (the call is allowed silently).

### `mode:context_injected`

- **Owner:** `hooks-mode`
- **When:** The fully-resolved mode context is injected into a
  `provider:request` and its SHA-256 hash differs from the last emission.
- **Payload:**
  ```python
  {
      "mode": str,
      "context_length": int,
      "content_hash": str,          # SHA-256 hex digest of resolved context
  }
  ```
- **Not emitted when:** The resolved context hash matches the last emitted
  hash. The hash is reset on every mode activation/clear, so the first
  injection in any new mode always emits.

## Consumer Pattern

Consumers should discover event names via `collect_contributions(...)` rather
than hard-coding them:

```python
async def on_session_ready(self, coordinator):
    # Discover all events contributed to the bus
    contributions = await coordinator.collect_contributions("observability.events")

    # Each contributor returned a list[str] — flatten
    all_events: list[str] = []
    for events_list in contributions:
        all_events.extend(events_list)

    # Filter to mode events and subscribe
    mode_events = [e for e in all_events if e.startswith("mode:")]
    for event_name in mode_events:
        coordinator.hooks.register(event_name, self._on_mode_event)

async def _on_mode_event(self, event_name: str, data: dict):
    self.logger.info("mode_event", event=event_name, **data)
    return HookResult()  # discard / no-op
```

Why discovery is preferred over hard-coded names:

- Future versions of the bundle may add or rename events; consumers built on
  `collect_contributions` keep working without code changes.
- Multiple bundles can contribute to the same channel; the consumer sees the
  union without coupling to any one bundle.
- The bundle's `register_contributor` calls remain the single source of
  truth for the event catalogue.

## Diagrams

- [`diagrams/mode-events-taxonomy.dot`](diagrams/mode-events-taxonomy.dot) —
  ownership and trigger relationships between kernel hooks and mode events.
- [`diagrams/mode-lifecycle.dot`](diagrams/mode-lifecycle.dot) — directed
  state machine showing when each event fires across the off/active states.

DOT source files only — no rendered SVG or PNG checked in. Render locally
with `dot -Tsvg <file.dot> -o <file.svg>` if needed.
