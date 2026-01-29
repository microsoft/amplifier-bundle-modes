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
    confirm_tools: list[str] = field(default_factory=list)  # Require user approval
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
        confirm_tools=tools_config.get("confirm", []),
        block_tools=tools_config.get("block", []),
        default_action=mode_config.get("default_action", "block"),
    )


class ModeDiscovery:
    """Discover mode definitions from search paths.

    Args:
        search_paths: Explicit paths to search for mode files
        working_dir: Project directory for `.amplifier/modes/` discovery.
            Falls back to cwd. Important for server deployments where
            process cwd differs from user's project directory.
    """

    def __init__(
        self, search_paths: list[Path] | None = None, working_dir: Path | None = None
    ):
        self._working_dir = working_dir or Path.cwd()
        self._search_paths = search_paths or self._default_search_paths()
        self._cache: dict[str, ModeDefinition] = {}

    def _default_search_paths(self) -> list[Path]:
        """Get default search paths for mode discovery."""
        paths = []

        # Project modes (highest precedence) - use working_dir instead of cwd
        project_modes = self._working_dir / ".amplifier" / "modes"
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

    def get_shortcuts(self) -> dict[str, str]:
        """Get mapping of shortcut -> mode name for all modes with shortcuts."""
        shortcuts: dict[str, str] = {}

        for base_path in self._search_paths:
            if not base_path.exists():
                continue
            for mode_file in base_path.glob("*.md"):
                name = mode_file.stem
                mode_def = self._cache.get(name) or parse_mode_file(mode_file)
                if mode_def:
                    self._cache[name] = mode_def
                    if mode_def.shortcut and mode_def.shortcut not in shortcuts:
                        shortcuts[mode_def.shortcut] = name

        return shortcuts

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
        """Get the currently active mode definition.

        Updates session_state["require_approval_tools"] for approval hook integration.
        This uses the generic key that approval hook respects, allowing modes to
        drive approval policy without the approval hook knowing about modes.
        """
        mode_name = self.coordinator.session_state.get("active_mode")
        if not mode_name:
            # Clear approval requirements when no mode is active
            self.coordinator.session_state["require_approval_tools"] = set()
            return None

        mode = self.discovery.find(mode_name)
        if mode:
            # Populate generic approval key - approval hook checks this
            self.coordinator.session_state["require_approval_tools"] = set(
                mode.confirm_tools
            )
        else:
            self.coordinator.session_state["require_approval_tools"] = set()

        return mode

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

        # Confirm tools: let approval hook handle it
        # (mode_confirm_tools is already set in session state by _get_active_mode)
        if tool_name in mode.confirm_tools:
            return HookResult(action="continue")

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


def _get_loaded_bundle_paths(coordinator: Any) -> list[Path]:
    """Get paths to all loaded bundles.

    Checks multiple sources for bundle information:
    1. coordinator.get_capability("bundle.paths") - list of bundle root paths
    2. coordinator.config.get("bundle_paths") - config-based paths
    3. coordinator.session_state.get("loaded_bundles") - runtime-loaded bundles
    4. ~/.amplifier/cache/ - scan for cached bundles with modes/ directories

    Returns:
        List of Path objects to bundle root directories.
    """
    paths: list[Path] = []

    # Try capability first (preferred method)
    try:
        bundle_paths = coordinator.get_capability("bundle.paths")
        if bundle_paths:
            if isinstance(bundle_paths, list):
                paths.extend(Path(p) for p in bundle_paths if p)
            elif isinstance(bundle_paths, str):
                paths.append(Path(bundle_paths))
    except Exception:
        pass

    # Try config
    try:
        config_paths = coordinator.config.get("bundle_paths", [])
        if config_paths:
            paths.extend(Path(p) for p in config_paths if p)
    except Exception:
        pass

    # Try session state (for dynamically loaded bundles)
    try:
        if hasattr(coordinator, "session_state"):
            loaded = coordinator.session_state.get("loaded_bundles", {})
            if isinstance(loaded, dict):
                # loaded_bundles might be {name: path} or {name: {path: ..., ...}}
                for value in loaded.values():
                    if isinstance(value, str):
                        paths.append(Path(value))
                    elif isinstance(value, dict) and "path" in value:
                        paths.append(Path(value["path"]))
            elif isinstance(loaded, list):
                paths.extend(Path(p) for p in loaded if p)
    except Exception:
        pass

    # Read bundle paths from settings.yaml (where `amplifier bundle add` stores them)
    settings_file = Path.home() / ".amplifier" / "settings.yaml"
    if settings_file.exists():
        try:
            settings = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
            bundle_config = settings.get("bundle", {})
            added_bundles = bundle_config.get("added", {})
            for bundle_path in added_bundles.values():
                if bundle_path and isinstance(bundle_path, str):
                    paths.append(Path(bundle_path))
        except Exception as e:
            logger.debug(f"Failed to read bundle paths from settings.yaml: {e}")

    # Scan bundle cache directory for bundles with modes/ directories
    # This catches bundles that were installed but not explicitly tracked
    cache_dir = Path.home() / ".amplifier" / "cache"
    if cache_dir.exists():
        for entry in cache_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("amplifier-bundle-"):
                modes_dir = entry / "modes"
                if modes_dir.exists() and modes_dir.is_dir():
                    paths.append(entry)

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique_paths: list[Path] = []
    for p in paths:
        if p not in seen and p.exists():
            seen.add(p)
            unique_paths.append(p)

    return unique_paths


async def mount(
    coordinator: Any, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Mount the mode hooks module.

    Config options:
        search_paths: Additional paths to search for mode files

    Note:
        Retrieves 'session.working_dir' capability for project mode discovery,
        falling back to cwd. This handles server deployments where the
        process cwd differs from the user's project directory.
    """
    config = config or {}

    # Initialize session state for modes
    if not hasattr(coordinator, "session_state"):
        coordinator.session_state = {}

    if "active_mode" not in coordinator.session_state:
        coordinator.session_state["active_mode"] = None

    # Get working_dir from capability (for server deployments where cwd is wrong)
    working_dir_str = coordinator.get_capability("session.working_dir")
    working_dir = Path(working_dir_str) if working_dir_str else None

    # Create discovery with config paths
    discovery = ModeDiscovery(working_dir=working_dir)

    # Auto-discover modes from this bundle (hooks-mode's own bundle)
    # When installed as part of amplifier-bundle-modes, the structure is:
    #   bundle-root/
    #   ├── modes/           <- We want to find this
    #   └── modules/
    #       └── hooks-mode/
    #           └── amplifier_module_hooks_mode/
    #               └── __init__.py  <- We are here
    module_file = Path(__file__)  # .../amplifier_module_hooks_mode/__init__.py
    hooks_mode_package = module_file.parent  # .../amplifier_module_hooks_mode/
    hooks_mode_module = hooks_mode_package.parent  # .../hooks-mode/
    modules_dir = hooks_mode_module.parent  # .../modules/
    bundle_root = modules_dir.parent  # bundle root
    bundle_modes_dir = bundle_root / "modes"

    if bundle_modes_dir.exists() and bundle_modes_dir.is_dir():
        logger.info(f"Auto-discovered bundle modes directory: {bundle_modes_dir}")
        discovery.add_search_path(bundle_modes_dir)

    # Cross-bundle mode discovery: find modes/ directories in all loaded bundles
    # Try to get bundle paths from coordinator capabilities or config
    bundle_paths = _get_loaded_bundle_paths(coordinator)
    for bundle_path in bundle_paths:
        bundle_modes = bundle_path / "modes"
        if bundle_modes.exists() and bundle_modes.is_dir():
            if bundle_modes not in discovery._search_paths:
                logger.info(f"Discovered modes from bundle: {bundle_modes}")
                discovery.add_search_path(bundle_modes)

    # Add additional search paths from config
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
    coordinator.hooks.register(
        "prompt:submit",
        hooks.handle_prompt_submit,
        priority=10,
        name="mode-context",
    )

    # Priority -20 ensures modes hook runs BEFORE approval hook (-10)
    # This allows modes to set session_state["require_approval_tools"]
    # before the approval hook checks it
    coordinator.hooks.register(
        "tool:pre",
        hooks.handle_tool_pre,
        priority=-20,
        name="mode-tools",
    )

    # Register capabilities for programmatic access to mode information
    mode_search_paths = [str(p) for p in discovery._search_paths]
    coordinator.register_capability("modes.search_paths", mode_search_paths)

    # Create a list of all discovered modes for easy access
    discovered_modes = []
    for name, desc in discovery.list_modes():
        discovered_modes.append({"name": name, "description": desc})
    coordinator.register_capability("modes.discovered", discovered_modes)

    # Inject permanent context listing all discovered modes and their locations
    # This helps the AI know about modes from all loaded bundles
    mode_list_lines = []
    for search_path in discovery._search_paths:
        if search_path.exists():
            for mode_file in sorted(search_path.glob("*.md")):
                mode_def = parse_mode_file(mode_file)
                if mode_def:
                    mode_list_lines.append(
                        f"- **{mode_def.name}**: {mode_def.description} (from {search_path})"
                    )

    if mode_list_lines:
        modes_context = (
            """<system-reminder source="discovered-modes">
## All Discovered Modes

The following modes are available from all loaded bundles:

"""
            + "\n".join(mode_list_lines)
            + """

When the user runs /modes, list ALL of the above modes. These include modes from multiple bundles.
</system-reminder>"""
        )
        coordinator.session_state["modes_discovery_context"] = modes_context

        # Register a hook to inject this context on first prompt
        async def inject_modes_list(_event: str, _data: dict) -> "HookResult":
            from amplifier_core.models import HookResult

            ctx = coordinator.session_state.pop("modes_discovery_context", None)
            if ctx:
                return HookResult(
                    action="inject_context",
                    context_injection=ctx,
                    context_injection_role="system",
                    ephemeral=False,
                )
            return HookResult(action="continue")

        coordinator.hooks.register(
            "prompt:submit",
            inject_modes_list,
            priority=5,  # Run before other hooks
            name="modes-discovery-list",
        )

    return {
        "name": "hooks-mode",
        "version": "1.0.0",
        "description": "Generic mode hooks for context injection and tool moderation",
    }


# Exports for external use
__all__ = [
    "ModeDefinition",
    "ModeDiscovery",
    "ModeHooks",
    "mount",
    "parse_mode_file",
]
