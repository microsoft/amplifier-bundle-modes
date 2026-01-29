"""Mode Tool Module

Provides a tool for agents to activate and deactivate modes.
This bridges the gap between the agent understanding mode commands
and actually setting session_state["active_mode"] for enforcement.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ModeTool:
    """Tool for activating and deactivating modes."""

    def __init__(self, coordinator: Any):
        self.coordinator = coordinator

    @property
    def name(self) -> str:
        return "mode"

    @property
    def description(self) -> str:
        return """Activate or deactivate a mode to change runtime behavior.

Modes modify how tools are allowed/blocked and inject context guidance.

Usage:
- Activate a mode: {"action": "activate", "mode": "plan"}
- Deactivate current mode: {"action": "deactivate"}
- List available modes: {"action": "list"}
- Get current mode: {"action": "current"}

When a mode is activated:
- Tool policies are enforced (safe/warn/block)
- Mode-specific guidance is injected into context

The user triggers modes with /mode <name> or /mode off commands.
You should call this tool to actually activate/deactivate the mode."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["activate", "deactivate", "list", "current"],
                    "description": "Action to perform",
                },
                "mode": {
                    "type": "string",
                    "description": "Mode name to activate (required for 'activate' action)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, params: dict) -> dict:
        """Execute the mode tool."""
        action = params.get("action")

        if action == "current":
            return self._get_current_mode()
        elif action == "list":
            return self._list_modes()
        elif action == "deactivate":
            return self._deactivate_mode()
        elif action == "activate":
            mode_name = params.get("mode")
            if not mode_name:
                return {
                    "success": False,
                    "error": "Mode name required for activate action",
                }
            return self._activate_mode(mode_name)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    def _get_current_mode(self) -> dict:
        """Get the currently active mode."""
        active = self.coordinator.session_state.get("active_mode")
        return {
            "success": True,
            "active_mode": active,
            "message": f"Current mode: {active}" if active else "No mode active",
        }

    def _list_modes(self) -> dict:
        """List all available modes."""
        discovery = self.coordinator.session_state.get("mode_discovery")
        if not discovery:
            return {
                "success": False,
                "error": "Mode discovery not initialized. Is hooks-mode loaded?",
            }

        modes = discovery.list_modes()
        return {
            "success": True,
            "modes": [{"name": name, "description": desc} for name, desc in modes],
            "count": len(modes),
        }

    def _activate_mode(self, mode_name: str) -> dict:
        """Activate a mode."""
        discovery = self.coordinator.session_state.get("mode_discovery")
        if not discovery:
            return {
                "success": False,
                "error": "Mode discovery not initialized. Is hooks-mode loaded?",
            }

        # Check if mode exists
        mode_def = discovery.find(mode_name)
        if not mode_def:
            available = [name for name, _ in discovery.list_modes()]
            return {
                "success": False,
                "error": f"Mode '{mode_name}' not found. Available: {', '.join(available)}",
            }

        # Activate the mode
        self.coordinator.session_state["active_mode"] = mode_name

        # Reset warned tools when switching modes
        mode_hooks = self.coordinator.session_state.get("mode_hooks")
        if mode_hooks:
            mode_hooks.reset_warnings()

        logger.info(f"Activated mode: {mode_name}")

        return {
            "success": True,
            "active_mode": mode_name,
            "description": mode_def.description,
            "message": f"Mode '{mode_name}' activated. {mode_def.description}",
            "tool_policies": {
                "safe": mode_def.safe_tools,
                "warn": mode_def.warn_tools,
                "confirm": mode_def.confirm_tools,
                "block": mode_def.block_tools,
                "default": mode_def.default_action,
            },
        }

    def _deactivate_mode(self) -> dict:
        """Deactivate the current mode."""
        previous = self.coordinator.session_state.get("active_mode")
        self.coordinator.session_state["active_mode"] = None

        # Reset warned tools
        mode_hooks = self.coordinator.session_state.get("mode_hooks")
        if mode_hooks:
            mode_hooks.reset_warnings()

        logger.info(f"Deactivated mode: {previous}")

        return {
            "success": True,
            "previous_mode": previous,
            "message": f"Mode '{previous}' deactivated."
            if previous
            else "No mode was active.",
        }


async def mount(
    coordinator: Any, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Mount the mode tool module."""
    tool = ModeTool(coordinator)

    # Register the tool
    coordinator.register_tool(tool)

    return {
        "name": "tool-mode",
        "version": "1.0.0",
        "description": "Tool for activating and deactivating modes",
    }


__all__ = ["ModeTool", "mount"]
