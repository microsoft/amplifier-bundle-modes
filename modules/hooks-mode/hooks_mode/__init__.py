"""Generic Mode Hooks Module

Provides context injection and tool moderation for user-defined modes.

Modes are defined in markdown files with YAML frontmatter:
- YAML frontmatter contains tool policies (safe/warn/block lists)
- Markdown body is injected as context when mode is active

The hook reads mode definitions dynamically, allowing users to create
custom modes without writing any Python code.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from amplifier_core.models import HookResult

logger = logging.getLogger(__name__)


@dataclass
class ModeDefinition:
    """Parsed mode definition from a mode file."""

    name: str
    description: str = ""
    shortcut: str | None = None
    context: str = ""  # Markdown body - injected when mode active
    safe_tools: list[str] = field(default_factory=list)
    warn_tools: list[str] = field(default_factory=list)
    block_tools: list[str] = field(default_factory=list)
    default_action: str = "block"  # "block" or "allow"


def parse_mode_file(file_path: Path) -> ModeDefinition | None:
    """Parse a mode definition from a markdown file with YAML frontmatter.

    Expected format:
    ---
    mode:
      name: plan
      description: Think and discuss
      shortcut: plan
      tools:
        safe: [read_file, grep]
        warn: [bash]
      default_action: block
    ---

    # Mode Context

    This markdown content is injected when the mode is active...
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read mode file {file_path}: {e}")
        return None

    # Parse YAML frontmatter
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not frontmatter_match:
        logger.warning(f"Mode file {file_path} missing YAML frontmatter")
        return None

    yaml_content = frontmatter_match.group(1)
    markdown_body = frontmatter_match.group(2).strip()

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        logger.warning(f"Invalid YAML in mode file {file_path}: {e}")
        return None

    if not parsed or "mode" not in parsed:
        logger.warning(f"Mode file {file_path} missing 'mode:' section")
        return None

    mode_config = parsed["mode"]
    tools_config = mode_config.get("tools", {})

    return ModeDefinition(
        name=mode_config.get("name", file_path.stem),
        description=mode_config.get("description", ""),
        shortcut=mode_config.get("shortcut"),
        context=markdown_body,
        safe_tools=tools_config.get("safe", []),
        warn_tools=tools_config.get("warn", []),
        block_tools=tools_config.get("block", []),
        default_action=mode_config.get("default_action", "block"),
    )


class ModeDiscovery:
    """Discover mode definitions from search paths."""

    def __init__(self, search_paths: list[Path] | None = None):
        self._search_paths = search_paths or self._default_search_paths()
        self._cache: dict[str, ModeDefinition] = {}

    def _default_search_paths(self) -> list[Path]:
        """Get default search paths for mode discovery."""
        paths = []

        # Project modes (highest precedence)
        project_modes = Path.cwd() / ".amplifier" / "modes"
        if project_modes.exists():
            paths.append(project_modes)

        # User modes
        user_modes = Path.home() / ".amplifier" / "modes"
        if user_modes.exists():
            paths.append(user_modes)

        return paths

    def add_search_path(self, path: Path) -> None:
        """Add a search path (e.g., from bundle)."""
        if path.exists() and path not in self._search_paths:
            self._search_paths.append(path)

    def find(self, name: str) -> ModeDefinition | None:
        """Find a mode definition by name."""
        # Check cache first
        if name in self._cache:
            return self._cache[name]

        # Search paths
        for base_path in self._search_paths:
            mode_file = base_path / f"{name}.md"
            if mode_file.exists():
                mode_def = parse_mode_file(mode_file)
                if mode_def:
                    self._cache[name] = mode_def
                    return mode_def

        return None

    def list_modes(self) -> list[tuple[str, str]]:
        """List all available modes as (name, description) tuples."""
        modes: dict[str, str] = {}

        for base_path in self._search_paths:
            if not base_path.exists():
                continue
            for mode_file in base_path.glob("*.md"):
                name = mode_file.stem
                if name not in modes:  # First match wins (precedence)
                    mode_def = parse_mode_file(mode_file)
                    if mode_def:
                        modes[name] = mode_def.description
                        self._cache[name] = mode_def

        return sorted(modes.items())

    def clear_cache(self) -> None:
        """Clear the mode definition cache."""
        self._cache.clear()


class ModeHooks:
    """Generic mode enforcement via hooks."""

    def __init__(self, coordinator: Any, discovery: ModeDiscovery):
        self.coordinator = coordinator
        self.discovery = discovery
        self.warned_tools: set[str] = set()

    def _get_active_mode(self) -> ModeDefinition | None:
        """Get the currently active mode definition."""
        mode_name = self.coordinator.session_state.get("active_mode")
        if not mode_name:
            return None
        return self.discovery.find(mode_name)

    async def handle_prompt_submit(self, _event: str, _data: dict) -> "HookResult":
        """Inject mode context on prompt submission."""
        from amplifier_core.models import HookResult

        mode = self._get_active_mode()
        if not mode or not mode.context:
            return HookResult(action="continue")

        # Wrap context in system-reminder tags
        context_block = f"""<system-reminder source="mode-{mode.name}">
{mode.context}
</system-reminder>"""

        return HookResult(
            action="inject_context",
            context_injection=context_block,
            context_injection_role="system",
            ephemeral=True,
        )

    async def handle_tool_pre(self, _event: str, data: dict) -> "HookResult":
        """Moderate tools based on active mode policy."""
        from amplifier_core.models import HookResult

        mode = self._get_active_mode()
        if not mode:
            return HookResult(action="continue")

        tool_name = data.get("tool_name", "")

        # Safe tools: always allow
        if tool_name in mode.safe_tools:
            return HookResult(action="continue")

        # Explicitly blocked tools: always deny
        if tool_name in mode.block_tools:
            return HookResult(
                action="deny",
                reason=f"Mode '{mode.name}': '{tool_name}' is blocked. {mode.description}",
            )

        # Warn-first tools: warn once, then allow
        if tool_name in mode.warn_tools:
            warn_key = f"{mode.name}:{tool_name}"
            if warn_key not in self.warned_tools:
                self.warned_tools.add(warn_key)
                return HookResult(
                    action="deny",
                    reason=f"Mode '{mode.name}': '{tool_name}' requires confirmation. "
                    f"Call again if this is appropriate for {mode.name} mode.",
                )
            return HookResult(action="continue")

        # Default action for unlisted tools
        if mode.default_action == "allow":
            return HookResult(action="continue")

        # Default is block
        return HookResult(
            action="deny",
            reason=f"Mode '{mode.name}': '{tool_name}' is not in the allowed list. "
            f"Use /mode off to exit {mode.name} mode.",
        )

    def reset_warnings(self) -> None:
        """Reset warned tools (called when switching modes)."""
        self.warned_tools.clear()


def mount(coordinator: Any, config: dict) -> Any:
    """Mount the mode hooks module.

    Config options:
        search_paths: Additional paths to search for mode files
    """
    # Initialize session state for modes
    if not hasattr(coordinator, "session_state"):
        coordinator.session_state = {}

    if "active_mode" not in coordinator.session_state:
        coordinator.session_state["active_mode"] = None

    # Create discovery with config paths
    discovery = ModeDiscovery()

    # Add bundle search paths from config
    extra_paths = config.get("search_paths", [])
    for path_str in extra_paths:
        discovery.add_search_path(Path(path_str))

    # Store discovery in session state for app access
    coordinator.session_state["mode_discovery"] = discovery

    # Create hooks instance
    hooks = ModeHooks(coordinator, discovery)

    # Store hooks in session state for mode switching (to reset warnings)
    coordinator.session_state["mode_hooks"] = hooks

    # Register hooks
    unregister_prompt = coordinator.hooks.register(
        "prompt:submit",
        hooks.handle_prompt_submit,
        priority=10,
        name="mode-context",
    )

    unregister_tool = coordinator.hooks.register(
        "tool:pre",
        hooks.handle_tool_pre,
        priority=5,
        name="mode-tools",
    )

    def cleanup():
        unregister_prompt()
        unregister_tool()

    return cleanup


# Exports for external use
__all__ = [
    "ModeDefinition",
    "ModeDiscovery",
    "ModeHooks",
    "mount",
    "parse_mode_file",
]
