"""Mode management tool for agent-initiated mode transitions.

Exposes a 'mode' tool that lets agents programmatically manage modes.
Requires hooks-mode to be mounted (reads session_state["mode_discovery"]).
"""

from __future__ import annotations

import logging
from typing import Any

from .events import (
    ALL_EVENTS,
    MODE_ACTIVATED,
    MODE_ACTIVATION_GATED,
    MODE_CHANGED,
    MODE_CLEARED,
    MODE_TRANSITION_DENIED,
)

logger = logging.getLogger(__name__)

__amplifier_module_type__ = "tool"


class ToolResult:
    """Minimal ToolResult for when amplifier_core is not available."""

    def __init__(
        self,
        success: bool = True,
        output: Any = None,
        error: dict[str, Any] | None = None,
    ):
        self.success = success
        self.output = output
        self.error = error

    def __str__(self) -> str:
        if self.error:
            return str(self.error)
        return str(self.output) if self.output is not None else ""


# Try to import the real ToolResult from amplifier_core
try:
    from amplifier_core import ToolResult  # type: ignore[assignment]
except ImportError:
    pass  # Use our minimal fallback above


class ModeTool:
    """Tool for agent-initiated mode management.

    Operations:
        list    - List all available modes
        current - Show the currently active mode
        set     - Activate a mode (subject to gate policy)
        clear   - Deactivate the current mode

    Gate policies (from config):
        auto    - Agent changes freely
        warn    - First call denied with reminder; retry proceeds
        confirm - Requires user approval via hooks-approval

    Event emission pattern follows the delegate tool convention
    (amplifier-foundation/modules/tool-delegate): bare ``await hooks.emit(...)``
    with no per-emit try/except. A single outer try/except per handler method
    catches unexpected failures (including rare bridge/serialization errors) and
    returns a clean ToolResult rather than letting exceptions escape to the LLM.
    This is distinct from hook handlers (hooks-mode) which use per-emit try/except
    to guarantee HookResult delivery to the kernel even when emit fails —
    fail-open observability, fail-closed security.
    """

    name = "mode"
    description = (
        "Manage runtime modes. Operations: 'set' (activate a mode), "
        "'clear' (deactivate), 'list' (show available), 'current' (show active). "
        "Mode transitions may require confirmation depending on gate policy."
    )

    def __init__(self, config: dict[str, Any], coordinator: Any):
        self.config = config
        self.coordinator = coordinator
        self.gate_policy: str = config.get("gate_policy", "warn")
        self._warned_transitions: set[str] = set()

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["set", "clear", "list", "current"],
                    "description": "Operation to perform",
                },
                "name": {
                    "type": "string",
                    "description": "Mode name (required for 'set' operation)",
                },
            },
            "required": ["operation"],
        }

    def _get_discovery(self) -> Any:
        """Get ModeDiscovery from session_state."""
        return self.coordinator.session_state.get("mode_discovery")

    def _get_hooks(self) -> Any:
        """Get ModeHooks from session_state."""
        return self.coordinator.session_state.get("mode_hooks")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a mode operation."""
        operation = input.get("operation", "")

        # Validate hooks-mode is mounted
        discovery = self._get_discovery()
        if discovery is None:
            return ToolResult(
                success=False,
                error={
                    "code": "hooks_mode_not_mounted",
                    "message": (
                        "hooks-mode module is not mounted. "
                        "tool-mode requires hooks-mode to be mounted first. "
                        "Add hooks-mode to your behavior's hooks section."
                    ),
                },
            )

        if operation == "list":
            return await self._handle_list(discovery)
        elif operation == "current":
            return await self._handle_current(discovery)
        elif operation == "set":
            return await self._handle_set(input, discovery)
        elif operation == "clear":
            return await self._handle_clear()
        else:
            return ToolResult(
                success=False,
                error={
                    "code": "invalid_operation",
                    "message": f"Unknown operation '{operation}'. Use: set, clear, list, current",
                },
            )

    async def _handle_list(self, discovery: Any) -> ToolResult:
        """List all available modes."""
        modes_list = discovery.list_modes()
        active = self.coordinator.session_state.get("active_mode")
        return ToolResult(
            success=True,
            output={
                "active_mode": active,
                "modes": [
                    {"name": name, "description": desc, "source": source}
                    for name, desc, source in modes_list
                ],
            },
        )

    async def _handle_current(self, discovery: Any) -> ToolResult:
        """Show the currently active mode."""
        active = self.coordinator.session_state.get("active_mode")
        if not active:
            return ToolResult(
                success=True,
                output={
                    "active_mode": None,
                    "message": "No mode is currently active.",
                },
            )

        mode_def = discovery.find(active)
        if not mode_def:
            return ToolResult(
                success=True,
                output={
                    "active_mode": active,
                    "message": f"Mode '{active}' is active but its definition was not found.",
                },
            )

        return ToolResult(
            success=True,
            output={
                "active_mode": active,
                "description": mode_def.description,
                "safe_tools": mode_def.safe_tools,
                "warn_tools": mode_def.warn_tools,
                "confirm_tools": mode_def.confirm_tools,
                "block_tools": mode_def.block_tools,
                "default_action": mode_def.default_action,
            },
        )

    async def _handle_set(self, input: dict[str, Any], discovery: Any) -> ToolResult:
        """Activate a mode (subject to gate policy)."""
        name = input.get("name")
        if not name:
            return ToolResult(
                success=False,
                error={
                    "code": "missing_name",
                    "message": "The 'name' parameter is required for 'set' operation.",
                },
            )

        # Validate mode exists
        mode_def = discovery.find(name)
        if not mode_def:
            available = discovery.list_modes()
            return ToolResult(
                success=False,
                error={
                    "code": "mode_not_found",
                    "message": f"Mode '{name}' not found.",
                    "available_modes": [n for n, _d, _s in available],
                },
            )

        # Outer try/except (delegate tool pattern): catches any unexpected failure
        # including rare bridge/serialization errors from hooks.emit(). Individual
        # emits are bare awaits — no per-emit wrapping.
        try:
            # Check allowed_transitions from current mode (if any)
            current_mode_name = self.coordinator.session_state.get("active_mode")
            if current_mode_name:
                current_mode_def = (
                    discovery.find(current_mode_name) if discovery else None
                )
                if (
                    current_mode_def
                    and current_mode_def.allowed_transitions is not None
                    and name not in current_mode_def.allowed_transitions
                ):
                    allowed = (
                        ", ".join(current_mode_def.allowed_transitions) or "(none)"
                    )
                    await self.coordinator.hooks.emit(
                        MODE_TRANSITION_DENIED,
                        {
                            "from_mode": current_mode_name,
                            "to_mode": name,
                            "allowed_transitions": list(
                                current_mode_def.allowed_transitions
                            ),
                        },
                    )
                    return ToolResult(
                        success=False,
                        error={
                            "code": "transition_denied",
                            "message": (
                                f"Transition from '{current_mode_name}' to '{name}' is not allowed. "
                                f"Allowed transitions: {allowed}."
                            ),
                        },
                    )

            # Apply gate policy
            if self.gate_policy == "warn":
                warn_key = f"set:{name}"
                if warn_key not in self._warned_transitions:
                    self._warned_transitions.add(warn_key)
                    await self.coordinator.hooks.emit(
                        MODE_ACTIVATION_GATED,
                        {
                            "gate_policy": self.gate_policy,
                            "target_mode": name,
                            "description": mode_def.description,
                            "from_mode": self.coordinator.session_state.get(
                                "active_mode"
                            ),
                        },
                    )
                    return ToolResult(
                        success=False,
                        output={
                            "status": "denied",
                            "denied_mode": name,
                            "user_instruction": (
                                f"Inform the user: I'd like to switch to '{name}' mode "
                                f"({mode_def.description}). You can switch manually with "
                                f"/mode {name} or I can retry to proceed."
                            ),
                        },
                    )

            elif self.gate_policy == "confirm":
                await self.coordinator.hooks.emit(
                    MODE_ACTIVATION_GATED,
                    {
                        "gate_policy": self.gate_policy,
                        "target_mode": name,
                        "description": mode_def.description,
                        "from_mode": self.coordinator.session_state.get("active_mode"),
                    },
                )
                return ToolResult(
                    success=False,
                    output={
                        "status": "denied",
                        "denied_mode": name,
                        "user_instruction": (
                            f"Inform the user: I'd like to switch to '{name}' mode "
                            f"({mode_def.description}). You can switch manually with "
                            f"/mode {name} or grant permission for me to manage "
                            f"mode transitions."
                        ),
                    },
                )

            # Gate passed (auto, or warn retry) - activate the mode
            return await self._activate_mode(name, mode_def)

        except Exception:
            logger.error("_handle_set failed unexpectedly", exc_info=True)
            return ToolResult(
                success=False,
                error={
                    "code": "internal_error",
                    "message": "An unexpected error occurred during mode set.",
                },
            )

    async def _activate_mode(self, name: str, mode_def: Any) -> ToolResult:
        """Activate a mode: emit event, update session state, reset warnings, return info.

        Emit-before-state-change pattern (matching delegate tool): the event fires
        before session state is mutated. If the emit raises unexpectedly, the caller's
        outer try/except returns a failure and state is never changed — keeping the
        observable state and the ToolResult consistent.
        """
        # Capture previous mode BEFORE any state write
        previous_mode = self.coordinator.session_state.get("active_mode")

        # Build payload before state change
        if previous_mode is None:
            event = MODE_ACTIVATED
            payload: dict[str, Any] = {
                "mode": name,
                "description": mode_def.description,
                "default_action": mode_def.default_action,
                "safe_tools": mode_def.safe_tools,
                "warn_tools": mode_def.warn_tools,
                "confirm_tools": mode_def.confirm_tools,
                "block_tools": mode_def.block_tools,
            }
        else:
            event = MODE_CHANGED
            payload = {
                "from_mode": previous_mode,
                "to_mode": name,
                "description": mode_def.description,
                "default_action": mode_def.default_action,
                "safe_tools": mode_def.safe_tools,
                "warn_tools": mode_def.warn_tools,
                "confirm_tools": mode_def.confirm_tools,
                "block_tools": mode_def.block_tools,
            }

        # Emit FIRST (before state change) — bare await, delegate tool pattern.
        # If this raises, the caller's outer try/except handles it and state is
        # never mutated, keeping observable state consistent with the return value.
        await self.coordinator.hooks.emit(event, payload)

        # Apply state changes only after emit succeeds
        self.coordinator.session_state["active_mode"] = name
        hooks = self._get_hooks()
        if hooks:
            hooks.reset_warnings()

        logger.info("Mode activated: %s (gate_policy=%s)", name, self.gate_policy)

        # Build restricted tools summary
        restricted: dict[str, list[str]] = {}
        if mode_def.warn_tools:
            restricted["warn"] = mode_def.warn_tools
        if mode_def.confirm_tools:
            restricted["confirm"] = mode_def.confirm_tools
        if mode_def.block_tools:
            restricted["block"] = mode_def.block_tools

        return ToolResult(
            success=True,
            output={
                "status": "activated",
                "mode": name,
                "description": mode_def.description,
                "safe_tools": mode_def.safe_tools,
                "restricted_tools": restricted,
                "default_action": mode_def.default_action,
                "note": "Your available tools have changed. Review tool policies before proceeding.",
            },
        )

    async def _handle_clear(self) -> ToolResult:
        """Deactivate the current mode (subject to allow_clear and gate policy)."""
        current_mode_name = self.coordinator.session_state.get("active_mode")

        # Outer try/except (delegate tool pattern): catches any unexpected failure
        # including rare bridge/serialization errors from hooks.emit(). Individual
        # emits are bare awaits — no per-emit wrapping.
        try:
            # Check allow_clear from current mode (if any)
            if current_mode_name:
                discovery = self._get_discovery()
                current_mode_def = (
                    discovery.find(current_mode_name) if discovery else None
                )
                if current_mode_def and not current_mode_def.allow_clear:
                    allowed = ""
                    if current_mode_def.allowed_transitions:
                        allowed = ", ".join(current_mode_def.allowed_transitions)
                    await self.coordinator.hooks.emit(
                        MODE_TRANSITION_DENIED,
                        {
                            "from_mode": current_mode_name,
                            "to_mode": None,
                            "allowed_transitions": list(
                                current_mode_def.allowed_transitions or []
                            ),
                        },
                    )
                    return ToolResult(
                        success=False,
                        error={
                            "code": "clear_denied",
                            "message": (
                                f"Cannot clear mode while in '{current_mode_name}'. "
                                f"Transition to a valid next mode instead."
                                + (
                                    f" Allowed transitions: {allowed}."
                                    if allowed
                                    else ""
                                )
                            ),
                        },
                    )

            # Apply gate policy (same as _handle_set)
            if self.gate_policy == "warn":
                warn_key = "clear"
                if warn_key not in self._warned_transitions:
                    self._warned_transitions.add(warn_key)
                    await self.coordinator.hooks.emit(
                        MODE_ACTIVATION_GATED,
                        {
                            "gate_policy": self.gate_policy,
                            "target_mode": None,
                            "from_mode": current_mode_name,
                        },
                    )
                    return ToolResult(
                        success=False,
                        output={
                            "status": "denied",
                            "user_instruction": (
                                "Inform the user: I'd like to clear the current mode"
                                + (
                                    f" ('{current_mode_name}')"
                                    if current_mode_name
                                    else ""
                                )
                                + " and remove all tool restrictions. "
                                "You can clear manually with /mode off or I can retry to proceed."
                            ),
                        },
                    )

            elif self.gate_policy == "confirm":
                await self.coordinator.hooks.emit(
                    MODE_ACTIVATION_GATED,
                    {
                        "gate_policy": self.gate_policy,
                        "target_mode": None,
                        "from_mode": current_mode_name,
                    },
                )
                return ToolResult(
                    success=False,
                    output={
                        "status": "denied",
                        "user_instruction": (
                            "Inform the user: I'd like to clear the current mode"
                            + (f" ('{current_mode_name}')" if current_mode_name else "")
                            + " and remove all tool restrictions. "
                            "You can clear manually with /mode off or grant permission "
                            "for me to manage mode transitions."
                        ),
                    },
                )

            # Gate passed — emit FIRST (before state change), delegate tool pattern.
            # If this raises, the caller's outer try/except handles it and state is
            # never mutated, keeping observable state consistent with the return value.
            if current_mode_name is not None:
                await self.coordinator.hooks.emit(
                    MODE_CLEARED, {"previous_mode": current_mode_name}
                )

            # Apply state changes only after emit succeeds
            previous = current_mode_name
            self.coordinator.session_state["active_mode"] = None
            hooks = self._get_hooks()
            if hooks:
                hooks.reset_warnings()
            # Reset gate warning memory so next set requires fresh confirmation
            self._warned_transitions.clear()

            logger.info("Mode cleared (was: %s)", previous)

            return ToolResult(
                success=True,
                output={
                    "status": "cleared",
                    "previous_mode": previous,
                    "message": "Mode deactivated. All tools are now unrestricted.",
                },
            )

        except Exception:
            logger.error("_handle_clear failed unexpectedly", exc_info=True)
            return ToolResult(
                success=False,
                error={
                    "code": "internal_error",
                    "message": "An unexpected error occurred during mode clear.",
                },
            )


async def mount(coordinator: Any, config: dict[str, Any] | None = None) -> None:
    """Mount the tool-mode module.

    Config:
        gate_policy: "auto" | "warn" | "confirm" (default: "warn")
    """
    config = config or {}

    # Validate hooks-mode is mounted (or will be - check at first use)
    if "mode_discovery" not in getattr(coordinator, "session_state", {}):
        logger.debug(
            "tool-mode: hooks-mode doesn't appear to be mounted yet. "
            "mode_discovery not found in session_state. "
            "The mode tool will validate at first use."
        )

    tool = ModeTool(config=config, coordinator=coordinator)
    await coordinator.mount("tools", tool, name=tool.name)
    # Contribute event catalogue to observability.events channel
    coordinator.register_contributor(
        "observability.events", "bundle-modes:tool-mode", lambda: ALL_EVENTS
    )
