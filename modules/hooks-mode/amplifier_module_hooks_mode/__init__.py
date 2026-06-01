"""Generic Mode Hooks Module

Provides context injection and tool moderation for user-defined modes.

Modes are defined in markdown files with YAML frontmatter:
- YAML frontmatter contains tool policies (safe/warn/block lists)
- Markdown body is injected as context when mode is active

The hook reads mode definitions dynamically, allowing users to create
custom modes without writing any Python code.
"""

from __future__ import annotations

import hashlib
import logging
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import yaml

if TYPE_CHECKING:
    from amplifier_core.models import HookResult

from .events import (  # noqa: F401
    ALL_EVENTS,
    MODE_CONTEXT_INJECTED,
    MODE_TOOL_BLOCKED,
    MODE_TOOL_WARNED,
)

logger = logging.getLogger(__name__)

# Authors may write shortcuts in any case (e.g. `shortcut: COSam`) for visual
# clarity in YAML; the parse pipeline lowercases at line ~179 before this
# check runs. The pattern intentionally accepts mixed case so that
# `_is_valid_shortcut` reflects what the system actually accepts at the
# author-input boundary, not what it stores internally after normalization.
# Slash-command dispatch in the CLI also lowercases all user input
# (`main.py:455`), so `/COSam` and `/cosam` are equivalent at lookup time.
_SHORTCUT_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"
_SHORTCUT_RE = re.compile(_SHORTCUT_PATTERN)


class ModeListing(NamedTuple):
    """One entry returned by ModeDiscovery.list_modes().

    Consumers that need to filter (e.g. the LLM-facing tool-mode) check
    ``entry.advertised``; human-facing surfaces (the CLI's ``/modes``) show all
    entries and decorate unadvertised ones with a ``(hidden)`` marker.
    """

    name: str
    description: str
    source: str
    advertised: bool


def _is_valid_shortcut(value: str) -> bool:
    """True iff `value` matches the shortcut identifier grammar (see design §7.3)."""
    return bool(_SHORTCUT_RE.match(value))


@dataclass
class ModeDefinition:
    """Parsed mode definition from a mode file."""

    name: str
    description: str = ""
    source: str = ""
    shortcut: str | None = None
    context: str = ""  # Markdown body - injected when mode active
    safe_tools: list[str] = field(default_factory=list)
    warn_tools: list[str] = field(default_factory=list)
    confirm_tools: list[str] = field(default_factory=list)  # Require user approval
    block_tools: list[str] = field(default_factory=list)
    default_action: str = "block"  # "block" or "allow"
    allowed_transitions: list[str] | None = None  # None = any transition allowed
    allow_clear: bool = True  # False = mode(clear) denied
    advertised: bool = (
        True  # NEW (Phase 2): False hides the mode from LLM-facing listings
    )
    contributes: dict[str, Any] = field(
        default_factory=dict
    )  # NEW (Phase 2): runtime overlay contributions


def parse_mode_file(file_path: Path) -> ModeDefinition | None:
    """Parse a mode definition from a markdown file with YAML frontmatter.

    Expected format (shortcut is optional; shown here with an explicit value):
    ---
    mode:
      name: plan
      description: Think and discuss
      shortcut: plan    # Optional — defaults to the mode's name (lowercased) when omitted
      tools:
        safe: [read_file, grep]
        warn: [bash]
      default_action: block
    ---

    # Mode Context

    This markdown content is injected when the mode is active...

    Shortcut resolution semantics:

    - If ``shortcut:`` is **absent**, the shortcut defaults to the resolved ``name``
      (or the filename stem when ``name`` is also absent).
    - If ``shortcut: false`` (YAML boolean), the shortcut is explicitly disabled;
      the mode remains activatable via ``/mode <name>``.
    - ``shortcut: "false"`` (quoted string) is a real shortcut named ``false``,
      distinct from the boolean opt-out.
    - Shortcuts are lowercase-normalized at parse time and validated against
      ``^[a-z][a-z0-9_-]*$``; invalid values log a WARNING and are dropped
      (the mode still loads and is activatable via ``/mode <name>``).

    Example with opt-out:
    ---
    mode:
      name: internal-only
      shortcut: false    # no /<name> alias registered; use /mode internal-only
      tools:
        safe: []
      default_action: block
    ---
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read mode file {file_path}: {e}")
        return None

    # Parse YAML frontmatter
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not frontmatter_match:
        logger.debug(
            f"Mode file {file_path} missing YAML frontmatter — not a mode file, skipping"
        )
        return None

    yaml_content = frontmatter_match.group(1)
    markdown_body = frontmatter_match.group(2).strip()

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        logger.warning(f"Invalid YAML in mode file {file_path}: {e}")
        return None

    if not parsed or "mode" not in parsed:
        logger.debug(
            f"Mode file {file_path} has no 'mode:' section — not a mode file, skipping"
        )
        return None

    mode_config = parsed["mode"]
    tools_config = mode_config.get("tools", {})

    resolved_name = mode_config.get("name", file_path.stem)

    if "shortcut" in mode_config:
        raw = mode_config["shortcut"]
        if raw is False or raw is None or raw == "" or raw == 0:
            shortcut = None
        elif isinstance(raw, bool):  # True — YAML truthy trap (yes/true/on)
            logger.warning(
                "Mode file %s: shortcut value %r is a YAML boolean, not a string. "
                "To disable the shortcut, use `shortcut: false`. "
                "To use the default (the mode's name), omit the field. "
                "Treating as absent for this load.",
                file_path,
                raw,
            )
            shortcut = resolved_name
        else:
            shortcut = str(raw).strip() or None
    else:
        shortcut = resolved_name

    if shortcut is not None:
        shortcut = shortcut.lower()

    if shortcut is not None and not _is_valid_shortcut(shortcut):
        logger.warning(
            "Mode file %s: shortcut %r is not a valid slash-command identifier "
            "(must match %s); no alias will be registered. "
            "The mode remains activatable via `/mode %s`.",
            file_path,
            shortcut,
            _SHORTCUT_PATTERN,
            resolved_name,
        )
        shortcut = None

    # Phase 2: Parse-time referential-integrity lints.
    contributes_block = mode_config.get("contributes", {}) or {}
    safe_list = list(tools_config.get("safe", []) or [])
    default_action_value = mode_config.get("default_action", "block")
    if (
        contributes_block.get("agents")
        and "delegate" not in safe_list
        and default_action_value != "allow"
    ):
        logger.warning(
            "Mode '%s' contributes agents but does not allow `delegate` in tools.safe "
            "(and default_action is not 'allow') — contributed agents will be unreachable "
            "by the LLM while this mode is active.",
            resolved_name,
        )
    if (
        contributes_block.get("skills")
        and "load_skill" not in safe_list
        and default_action_value != "allow"
    ):
        logger.warning(
            "Mode '%s' contributes skills but does not allow `load_skill` in tools.safe "
            "(and default_action is not 'allow') — contributed skills will be undiscoverable "
            "by the LLM while this mode is active.",
            resolved_name,
        )

    return ModeDefinition(
        name=resolved_name,
        description=mode_config.get("description", ""),
        shortcut=shortcut,
        context=markdown_body,
        safe_tools=tools_config.get("safe", []),
        warn_tools=tools_config.get("warn", []),
        confirm_tools=tools_config.get("confirm", []),
        block_tools=tools_config.get("block", []),
        default_action=mode_config.get("default_action", "block"),
        allowed_transitions=mode_config.get("allowed_transitions"),
        allow_clear=mode_config.get("allow_clear", True),
        advertised=mode_config.get("advertised", True),
        contributes=mode_config.get("contributes", {}) or {},
    )


class ModeDiscovery:
    """Discover mode definitions from search paths.

    Args:
        search_paths: Explicit paths to search for mode files
        working_dir: Project directory for `.amplifier/modes/` discovery.
            Falls back to cwd. Important for server deployments where
            process cwd differs from user's project directory.
        coordinator: Optional coordinator reference for lazy bundle discovery.
            When provided, modes directories from all composed bundles are
            auto-discovered on first access via the mention_resolver capability.
    """

    def __init__(
        self,
        search_paths: list[Path] | list[tuple[Path, str]] | None = None,
        working_dir: Path | None = None,
        coordinator: Any = None,
        deferred_paths: list[str] | None = None,
    ):
        self._working_dir = working_dir or Path.cwd()
        # Normalize search_paths: accept bare Paths (legacy) or (Path, source) tuples
        if search_paths is not None:
            normalized: list[tuple[Path, str]] = []
            for entry in search_paths:
                if isinstance(entry, tuple):
                    normalized.append(entry)
                else:
                    normalized.append((entry, ""))
            self._search_paths = normalized
        else:
            self._search_paths = self._default_search_paths()
        self._cache: dict[str, ModeDefinition] = {}
        self._coordinator = coordinator
        self._bundle_discovery_done = False
        self._deferred_paths = deferred_paths or []

    def _default_search_paths(self) -> list[tuple[Path, str]]:
        """Get default search paths for mode discovery."""
        paths: list[tuple[Path, str]] = []

        # Project modes (highest precedence) - use working_dir instead of cwd
        project_modes = self._working_dir / ".amplifier" / "modes"
        if project_modes.exists():
            paths.append((project_modes, "project"))

        # User modes
        user_modes = Path.home() / ".amplifier" / "modes"
        if user_modes.exists():
            paths.append((user_modes, "user"))

        return paths

    def add_search_path(self, path: Path, source: str = "") -> None:
        """Add a search path (e.g., from bundle)."""
        if path.exists() and path not in [p for p, _s in self._search_paths]:
            self._search_paths.append((path, source))

    def _ensure_bundle_discovery(self) -> None:
        """Lazily discover modes directories from all composed bundles.

        Deferred to first access because the mention_resolver capability
        is registered after all modules mount. By the time a user invokes
        /modes or activates a mode, all capabilities are available.
        """
        if self._bundle_discovery_done or self._coordinator is None:
            logger.debug(
                "Bundle discovery skipped: done=%s, coordinator=%s",
                self._bundle_discovery_done,
                self._coordinator is not None,
            )
            return
        self._bundle_discovery_done = True

        resolver = self._coordinator.get_capability("mention_resolver")
        if not resolver:
            logger.warning("Bundle mode discovery: no mention_resolver capability")
            return

        # The mention_resolver may be a BaseMentionResolver (has .bundles directly)
        # or an AppMentionResolver (wraps BaseMentionResolver as .foundation_resolver).
        # Reach through to whichever has the bundles dict.
        bundles = getattr(resolver, "bundles", None)
        if bundles is None:
            inner = getattr(resolver, "foundation_resolver", None)
            if inner:
                bundles = getattr(inner, "bundles", None)

        if not bundles:
            logger.warning(
                "Bundle mode discovery: no bundles dict found on resolver"
                " (type=%s, has_foundation=%s)",
                type(resolver).__name__,
                hasattr(resolver, "foundation_resolver"),
            )
            return

        logger.info(
            "Bundle mode discovery: scanning %d namespaces: %s",
            len(bundles),
            list(bundles.keys()),
        )
        for namespace, bundle in bundles.items():
            # Collect all candidate base paths for this bundle
            candidate_paths: list[Path] = []

            if hasattr(bundle, "base_path") and bundle.base_path:
                candidate_paths.append(Path(bundle.base_path))

            # Also check source_base_paths for multi-source bundles
            for sbp in getattr(bundle, "source_base_paths", None) or []:
                p = Path(sbp)
                if p not in candidate_paths:
                    candidate_paths.append(p)

            logger.debug(
                "Bundle '%s': candidate paths = %s", namespace, candidate_paths
            )
            for base in candidate_paths:
                bundle_modes = base / "modes"
                if bundle_modes.exists() and bundle_modes.is_dir():
                    mode_files = [f.stem for f in bundle_modes.glob("*.md")]
                    logger.info(
                        "Auto-discovered modes from bundle '%s': %s (files: %s)",
                        namespace,
                        bundle_modes,
                        mode_files,
                    )
                    self.add_search_path(bundle_modes, source=namespace)

        # Resolve deferred @mention paths
        if self._deferred_paths:
            for mention_path in self._deferred_paths:
                if not mention_path.startswith("@"):
                    logger.warning(
                        "Deferred path '%s' doesn't start with @, skipping",
                        mention_path,
                    )
                    continue

                # Parse @namespace:subpath
                without_at = mention_path[1:]
                if ":" in without_at:
                    namespace, subpath = without_at.split(":", 1)
                else:
                    namespace = without_at
                    subpath = ""

                if not bundles:
                    logger.warning(
                        "Cannot resolve '%s': no bundles available", mention_path
                    )
                    continue

                bundle = bundles.get(namespace)
                if not bundle:
                    logger.warning(
                        "Cannot resolve '%s': namespace '%s' not found in %s",
                        mention_path,
                        namespace,
                        list(bundles.keys()),
                    )
                    continue

                base = getattr(bundle, "base_path", None)
                if not base:
                    logger.warning(
                        "Cannot resolve '%s': bundle '%s' has no base_path",
                        mention_path,
                        namespace,
                    )
                    continue

                resolved = Path(base) / subpath if subpath else Path(base)
                if resolved.exists() and resolved.is_dir():
                    logger.info(
                        "Resolved deferred path '%s' -> %s", mention_path, resolved
                    )
                    self.add_search_path(resolved, source=namespace)
                else:
                    logger.warning(
                        "Resolved deferred path '%s' -> %s (does not exist)",
                        mention_path,
                        resolved,
                    )
            self._deferred_paths = []  # Clear after resolution

        logger.info(
            "Bundle mode discovery complete. Search paths: %s",
            self._search_paths,
        )

    def find(self, name: str) -> ModeDefinition | None:
        """Find a mode definition by name."""
        self._ensure_bundle_discovery()

        # Check cache first
        if name in self._cache:
            return self._cache[name]

        # Search paths
        for base_path, source_label in self._search_paths:
            mode_file = base_path / f"{name}.md"
            if mode_file.exists():
                mode_def = parse_mode_file(mode_file)
                if mode_def:
                    mode_def.source = source_label
                    self._cache[name] = mode_def
                    return mode_def

        return None

    def list_modes(self, **kwargs: Any) -> list[ModeListing]:
        """List all available modes as ModeListing entries.

        Returns ALL modes (advertised and unadvertised). Consumers that need to
        filter — e.g. the LLM-facing tool-mode — should check ``entry.advertised``
        and filter accordingly.  Human-facing surfaces (the CLI's ``/modes``)
        show all entries and mark unadvertised ones with a ``(hidden)`` indicator.

        The ``include_unadvertised`` keyword argument is still accepted for one
        release but is ignored; all modes are returned regardless.  Callers that
        pass it will receive a ``DeprecationWarning``.
        """
        if "include_unadvertised" in kwargs:
            warnings.warn(
                "include_unadvertised is deprecated and will be removed in a future "
                "release. list_modes() now always returns all modes; consumers should "
                "filter on ModeListing.advertised as needed.",
                DeprecationWarning,
                stacklevel=2,
            )

        self._ensure_bundle_discovery()
        modes: dict[str, ModeListing] = {}

        for base_path, source_label in self._search_paths:
            if not base_path.exists():
                continue
            for mode_file in base_path.glob("*.md"):
                name = mode_file.stem
                if name not in modes:  # First match wins (precedence)
                    mode_def = parse_mode_file(mode_file)
                    if mode_def:
                        mode_def.source = source_label
                        modes[name] = ModeListing(
                            name=name,
                            description=mode_def.description,
                            source=source_label,
                            advertised=mode_def.advertised,
                        )
                        self._cache[name] = mode_def

        return sorted(modes.values(), key=lambda m: m.name)

    def get_shortcuts(self) -> dict[str, str]:
        """Get mapping of shortcut -> mode name for all modes with shortcuts."""
        self._ensure_bundle_discovery()
        shortcuts: dict[str, str] = {}

        for base_path, _source_label in self._search_paths:
            if not base_path.exists():
                continue
            for mode_file in base_path.glob("*.md"):
                name = mode_file.stem
                # Always freshly parse each file so collision detection can compare
                # mode_def.name values across search paths (same-stem files in different
                # bundles may have different YAML name: fields).  Cache is updated with
                # first-wins semantics so find() callers see the highest-precedence mode_def.
                mode_def = parse_mode_file(mode_file)
                if mode_def:
                    if name not in self._cache:  # preserve first-wins cache precedence
                        self._cache[name] = mode_def
                    if mode_def.shortcut:
                        if mode_def.shortcut in shortcuts:
                            existing_name = shortcuts[mode_def.shortcut]
                            if existing_name != mode_def.name:
                                logger.info(
                                    "Shortcut collision: /%s claimed by mode %r (precedence) "
                                    "and again by mode %r (skipped). Set `shortcut:` explicitly "
                                    "on one of them to disambiguate, or `shortcut: false` to disable.",
                                    mode_def.shortcut,
                                    existing_name,
                                    mode_def.name,
                                )
                        else:
                            shortcuts[mode_def.shortcut] = mode_def.name

        return shortcuts

    def clear_cache(self) -> None:
        """Clear the mode definition cache."""
        self._cache.clear()


class ModeHooks:
    """Generic mode enforcement via hooks."""

    def __init__(
        self,
        coordinator: Any,
        discovery: ModeDiscovery,
        infrastructure_tools: set[str] | None = None,
    ):
        self.coordinator = coordinator
        self.discovery = discovery
        self.warned_tools: set[str] = set()
        self._last_context_hash: str | None = None
        self.infrastructure_tools: set[str] = (
            infrastructure_tools
            if infrastructure_tools is not None
            else {"mode", "todo"}
        )

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

    def _resolve_mentions(self, content: str) -> str:
        """Resolve @namespace:path mentions in mode context content.

        Lines that consist solely of an @-mention (e.g. ``@superpowers:context/foo.md``)
        are replaced with the content of the referenced file.  Lines whose mention
        cannot be resolved are removed rather than left as raw text so that the LLM
        never sees an unresolvable reference.

        The method is a no-op when:
        - the content contains no ``@`` character (fast path), or
        - no ``mention_resolver`` capability is registered on the coordinator.
        """
        if "@" not in content:
            return content

        resolver = self.coordinator.get_capability("mention_resolver")
        if not resolver:
            return content

        def _replace(match: re.Match[str]) -> str:
            mention = match.group(1)
            try:
                resolved_path = resolver.resolve(mention)
                if resolved_path is None:
                    logger.warning(
                        "mode @-mention resolution: could not resolve '%s' — line removed",
                        mention,
                    )
                    return ""
                file_content = Path(resolved_path).read_text(encoding="utf-8")
                return file_content
            except Exception as exc:
                logger.warning(
                    "mode @-mention resolution: failed to read '%s': %s — line removed",
                    mention,
                    exc,
                )
                return ""

        return re.sub(r"^\s*(@\S+:\S+)\s*$", _replace, content, flags=re.MULTILINE)

    async def handle_provider_request(self, _event: str, _data: dict) -> "HookResult":
        """Inject mode context on every provider request.

        Outer try/except (same shape as tool-mode's handler pattern): any unexpected
        exception in the handler body is caught and logged; context injection fails open
        (returns HookResult(action="continue")) so a handler bug never breaks a provider
        request. Emits are bare awaits — coordinator.hooks.emit() is infallible at the
        kernel level (hooks.rs:212-222), so per-emit guards are unnecessary.
        """
        from amplifier_core.models import HookResult

        try:
            mode = self._get_active_mode()
            if not mode:
                # B3 guard: detect session-resume state loss.
                # mode_runtime_overlay is constructed in-process and stored in
                # session_state, but session_state is not persisted across
                # process restarts.  If an overlay exists but active_mode is
                # None, the process was likely restarted (e.g. amplifier run
                # --resume) and the active_mode flag was lost.  The overlay
                # contributions are still registered with the coordinator from
                # the previous process, but the handler can no longer read
                # the mode name to inject context.  Log a loud WARNING so the
                # issue is visible in logs rather than silently missing.
                overlay_obj = self.coordinator.session_state.get("mode_runtime_overlay")
                if overlay_obj is not None and getattr(overlay_obj, "_scope_claims", None):
                    logger.warning(
                        "Mode runtime overlay exists but active_mode is None — "
                        "possible session-resume state loss. "
                        "Mode contributions will not be injected this turn."
                    )
                # Inject a positive signal that no mode is active, so the LLM has
                # an unambiguous reminder even when there's no mode to be in.
                # This prevents false claims about mode state across turns.
                no_mode_block = (
                    '<system-reminder source="mode-status">\n'
                    "No mode is currently active. "
                    'Use `mode(operation="list")` to see available modes '
                    'or `mode(operation="set", name="<name>")` to activate one.\n'
                    "</system-reminder>"
                )
                return HookResult(
                    action="inject_context",
                    context_injection=no_mode_block,
                    context_injection_role="system",
                    ephemeral=True,
                )
            if not mode.context:
                # Even if a mode is active but has no markdown body, we inject
                # a minimal reminder so the LLM always has a positive signal
                # for "I'm in mode X" rather than silent absence.
                context_block = (
                    f'<system-reminder source="mode-{mode.name}">\n'
                    f"MODE ACTIVE: {mode.name}\n"
                    f"</system-reminder>"
                )
                return HookResult(
                    action="inject_context",
                    context_injection=context_block,
                    context_injection_role="system",
                    ephemeral=True,
                )

            # Resolve any @namespace:path mentions in the mode body before injection
            resolved_context = self._resolve_mentions(mode.context)

            # Inject files declared in contributes.context (runtime_context_overlay
            # capability is populated by RuntimeOverlay.apply on activation).
            # Injection order: contributed-context first, then mode body — all
            # wrapped in one <system-reminder> block so the LLM sees a single
            # coherent context chunk rather than interleaved fragments.
            from amplifier_foundation import RUNTIME_CONTEXT_OVERLAY_CAPABILITY

            contributed_content = ""
            context_paths: list[str] = (
                self.coordinator.get_capability(RUNTIME_CONTEXT_OVERLAY_CAPABILITY) or []
            )
            if context_paths:
                # Build a newline-separated block of @-mentions; _resolve_mentions
                # replaces each standalone mention line with the file's content.
                path_block = "\n".join(str(p) for p in context_paths)
                resolved_paths = self._resolve_mentions(path_block)
                if resolved_paths.strip():
                    contributed_content = resolved_paths.rstrip("\n") + "\n\n"

            # Combine contributed context (if any) with the mode body
            full_context = contributed_content + resolved_context

            # Emit mode:context_injected only when the context has changed (hash-gated).
            # Nested emit is safe: mode:context_injected is a different event name from
            # provider:request, no handlers in this module listen on it, so there is no
            # recursive dispatch path.
            content_hash = hashlib.sha256(full_context.encode()).hexdigest()
            if content_hash != self._last_context_hash:
                self._last_context_hash = content_hash
                await self.coordinator.hooks.emit(
                    MODE_CONTEXT_INJECTED,
                    {
                        "mode": mode.name,
                        "context_length": len(full_context),
                        "content_hash": content_hash,
                    },
                )

            # Wrap context in system-reminder tags with explicit MODE ACTIVE banner
            context_block = (
                f'<system-reminder source="mode-{mode.name}">\n'
                f"MODE ACTIVE: {mode.name}\n"
                f"You are CURRENTLY in {mode.name} mode. It is already active — "
                f'do NOT call mode(set, "{mode.name}") to re-activate it. '
                f"Follow the guidance below.\n\n"
                f"{full_context}\n"
                f"</system-reminder>"
            )

            return HookResult(
                action="inject_context",
                context_injection=context_block,
                context_injection_role="system",
                ephemeral=True,
            )

        except Exception:
            logger.warning(
                "handle_provider_request error for mode '%s'; skipping context injection",
                self.coordinator.session_state.get("active_mode"),
                exc_info=True,
            )
            return HookResult(action="continue")

    async def handle_tool_pre(self, _event: str, data: dict) -> "HookResult":
        """Moderate tools based on active mode policy.

        Outer try/except (same shape as tool-mode's handler pattern): any unexpected
        exception in the handler body is caught, logged, and the handler fails closed
        (returns HookResult(action="deny")). A handler bug never silently drops the
        security decision. Emits are bare awaits — coordinator.hooks.emit() is
        infallible at the kernel level (hooks.rs:212-222), so per-emit guards are
        unnecessary.
        """
        from amplifier_core.models import HookResult

        try:
            mode = self._get_active_mode()
            if not mode:
                return HookResult(action="continue")

            tool_name = data.get("tool_name", "")

            # Infrastructure tools: always bypass the cascade
            if tool_name in self.infrastructure_tools:
                return HookResult(action="continue")

            # Safe tools: always allow
            if tool_name in mode.safe_tools:
                return HookResult(action="continue")

            # Explicitly blocked tools: always deny
            if tool_name in mode.block_tools:
                await self.coordinator.hooks.emit(
                    MODE_TOOL_BLOCKED,
                    {"tool_name": tool_name, "mode": mode.name, "reason": "block_list"},
                )
                return HookResult(
                    action="deny",
                    reason=f"Mode '{mode.name}': '{tool_name}' is blocked. {mode.description}",
                )

            # Confirm tools: let approval hook handle it
            # (require_approval_tools is already set in session state by _get_active_mode)
            if tool_name in mode.confirm_tools:
                return HookResult(action="continue")

            # Warn-first tools: warn once, then allow.
            # One event per decision: outcome="denied" on first call, outcome="allowed"
            # on retry.
            if tool_name in mode.warn_tools:
                warn_key = f"{mode.name}:{tool_name}"
                if warn_key not in self.warned_tools:
                    self.warned_tools.add(warn_key)
                    await self.coordinator.hooks.emit(
                        MODE_TOOL_WARNED,
                        {
                            "tool_name": tool_name,
                            "mode": mode.name,
                            "outcome": "denied",
                        },
                    )
                    return HookResult(
                        action="deny",
                        reason=f"Mode '{mode.name}': '{tool_name}' requires confirmation. "
                        f"Call again if this is appropriate for {mode.name} mode.",
                    )
                # Second+ call: tool has been warned and acknowledged; now allowed.
                await self.coordinator.hooks.emit(
                    MODE_TOOL_WARNED,
                    {"tool_name": tool_name, "mode": mode.name, "outcome": "allowed"},
                )
                return HookResult(action="continue")

            # Default action for unlisted tools
            if mode.default_action == "allow":
                return HookResult(action="continue")

            # Default is block
            await self.coordinator.hooks.emit(
                MODE_TOOL_BLOCKED,
                {"tool_name": tool_name, "mode": mode.name, "reason": "default_action"},
            )
            return HookResult(
                action="deny",
                reason=f"Mode '{mode.name}': '{tool_name}' is not in the allowed list. "
                f"Use /mode off to exit {mode.name} mode.",
            )

        except Exception:
            logger.warning(
                "handle_tool_pre error for tool '%s'; defaulting to deny",
                data.get("tool_name", "<unknown>"),
                exc_info=True,
            )
            return HookResult(action="deny")

    def _get_or_create_overlay(self) -> Any:
        """Get the singleton RuntimeOverlay for this session, creating it lazily.

        Stored in session_state so it survives across activations and
        deactivations within a single session, keeping refcounts coherent.
        """
        overlay = self.coordinator.session_state.get("mode_runtime_overlay")
        if overlay is None:
            from amplifier_foundation import RuntimeOverlay
            from .events import MODE_ACTIVATION_FAILED, MODE_TRANSITION_COMPLETED

            # TODO(Phase 3 de-dup): The overlay emits MODE_TRANSITION_COMPLETED /
            # MODE_ACTIVATION_FAILED on every apply/revoke.  The three handler
            # methods (handle_mode_activated, handle_mode_changed,
            # handle_mode_cleared) ALSO emit those same events directly, producing
            # duplicate events on the bus — one from the overlay and one from the
            # handler.  Two options for Phase 3 cleanup:
            #   (a) remove the handlers' manual emits (overlay already covers them)
            #   (b) make overlay's success/failure events optional (Phase 1 follow-up)
            overlay = RuntimeOverlay(
                self.coordinator,
                success_event=MODE_TRANSITION_COMPLETED,
                failure_event=MODE_ACTIVATION_FAILED,
            )
            self.coordinator.session_state["mode_runtime_overlay"] = overlay
        return overlay

    async def handle_mode_activated(self, _event: str, data: dict) -> "HookResult":
        """Apply the activated mode's contributions via RuntimeOverlay.

        On any failure (either overlay.apply() returning success=False, or an
        unexpected exception): clear active_mode so the session is not stuck in
        a half-activated state, emit mode:activation_failed, and return
        continue.  The RuntimeOverlay primitive handles atomic rollback of any
        partial contributions it applied before the failure.

        Payload key resolution (defensive, dual-key):
          Canonical:  data["name"]        (set by tool-mode since contract fix)
          Legacy:     data["mode"]        (tool-mode original key, kept for compat)
          Fallback:   session_state["active_mode"]  (set by tool-mode after emit)
        """
        from amplifier_core.models import HookResult
        from .events import MODE_ACTIVATION_FAILED, MODE_TRANSITION_COMPLETED

        mode_name = (
            data.get("name")
            or data.get("mode")
            or self.coordinator.session_state.get("active_mode")
        )
        if not mode_name:
            return HookResult(action="continue")

        try:
            mode_def = self.discovery.find(mode_name)
            if mode_def and mode_def.contributes:
                overlay = self._get_or_create_overlay()
                apply_result = await overlay.apply(
                    f"mode:{mode_name}", mode_def.contributes
                )
                if not apply_result.success:
                    # The overlay already rolled back partial contributions and
                    # emitted MODE_ACTIVATION_FAILED via its _emit method.
                    # Clear active_mode so the session reflects the failure.
                    self.coordinator.session_state["active_mode"] = None
                    return HookResult(action="continue")

            await self.coordinator.hooks.emit(
                MODE_TRANSITION_COMPLETED,
                {"mode": mode_name, "phase": "activated"},
            )
        except Exception as exc:
            logger.warning(
                "handle_mode_activated: overlay apply failed for mode '%s': %s",
                mode_name,
                exc,
                exc_info=True,
            )
            # Clear active_mode on unexpected exceptions too — the activation
            # did not complete successfully.
            self.coordinator.session_state["active_mode"] = None
            await self.coordinator.hooks.emit(
                MODE_ACTIVATION_FAILED,
                {"mode": mode_name, "error": str(exc)},
            )

        return HookResult(action="continue")

    async def handle_mode_changed(self, _event: str, data: dict) -> "HookResult":
        """Revoke old mode's scope, then apply new mode's scope.

        Payload key resolution (defensive, dual-key):
          Canonical:  data["old"] / data["new"]               (set by tool-mode since contract fix)
          Legacy:     data["from_mode"] / data["to_mode"]     (tool-mode original keys, kept for compat)
        Either may be falsy — defensive code costs nothing. On any error, emit
        mode:activation_failed and continue.
        """
        from amplifier_core.models import HookResult
        from .events import MODE_ACTIVATION_FAILED, MODE_TRANSITION_COMPLETED

        old_name = data.get("old") or data.get("from_mode")
        new_name = data.get("new") or data.get("to_mode")

        try:
            overlay = self._get_or_create_overlay()
            if old_name:
                await overlay.revoke(f"mode:{old_name}")
            if new_name:
                new_def = self.discovery.find(new_name)
                if new_def and new_def.contributes:
                    await overlay.apply(f"mode:{new_name}", new_def.contributes)

            await self.coordinator.hooks.emit(
                MODE_TRANSITION_COMPLETED,
                {"mode": new_name, "phase": "changed"},
            )
        except Exception as exc:
            logger.warning(
                "handle_mode_changed: overlay transition failed (old=%s, new=%s): %s",
                old_name,
                new_name,
                exc,
                exc_info=True,
            )
            await self.coordinator.hooks.emit(
                MODE_ACTIVATION_FAILED,
                {"mode": new_name, "error": str(exc)},
            )

        return HookResult(action="continue")

    async def handle_mode_cleared(self, _event: str, data: dict) -> "HookResult":
        """Revoke the cleared mode's scope.

        Payload key resolution (defensive, dual-key):
          Canonical:  data["name"]            (set by tool-mode since contract fix)
          Legacy:     data["previous_mode"]   (tool-mode original key, kept for compat)
          Fallback:   session_state["active_mode"]  (pre-cleared state if available)
        On any error, emit mode:activation_failed and continue (revocation is
        best-effort — leftover state is far better than a broken transition).
        """
        from amplifier_core.models import HookResult
        from .events import MODE_ACTIVATION_FAILED, MODE_TRANSITION_COMPLETED

        mode_name = (
            data.get("name")
            or data.get("previous_mode")
            or self.coordinator.session_state.get("active_mode")
        )
        if not mode_name:
            return HookResult(action="continue")

        try:
            overlay = self._get_or_create_overlay()
            await overlay.revoke(f"mode:{mode_name}")
            await self.coordinator.hooks.emit(
                MODE_TRANSITION_COMPLETED,
                {"mode": mode_name, "phase": "cleared"},
            )
        except Exception as exc:
            logger.warning(
                "handle_mode_cleared: overlay revoke failed for mode '%s': %s",
                mode_name,
                exc,
                exc_info=True,
            )
            await self.coordinator.hooks.emit(
                MODE_ACTIVATION_FAILED,
                {"mode": mode_name, "error": str(exc)},
            )

        return HookResult(action="continue")

    def reset_warnings(self) -> None:
        """Reset warned tools and context-injected hash (called when switching modes)."""
        self.warned_tools.clear()
        self._last_context_hash = None


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

    # Separate @mention paths (deferred) from filesystem paths (immediate)
    extra_paths = config.get("search_paths", [])
    deferred_paths: list[str] = []
    immediate_paths: list[Path] = []
    for path_str in extra_paths:
        if isinstance(path_str, str) and path_str.startswith("@"):
            deferred_paths.append(path_str)
        else:
            p = Path(str(path_str)).expanduser()
            if not p.is_absolute():
                # Resolve relative paths against working_dir, not cwd
                p = (working_dir or Path.cwd()) / p
            p = p.resolve()
            immediate_paths.append(p)

    # Create discovery with coordinator for lazy bundle discovery
    discovery = ModeDiscovery(
        working_dir=working_dir,
        coordinator=coordinator,
        deferred_paths=deferred_paths,
    )

    # Auto-discover bundle's modes directory
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
        discovery.add_search_path(bundle_modes_dir, source="modes")
    else:
        logger.warning(f"Bundle modes directory not found at {bundle_modes_dir}")

    # Add immediate (non-@mention) search paths
    for p in immediate_paths:
        discovery.add_search_path(p, source="config")

    # Store discovery in session state for app access
    coordinator.session_state["mode_discovery"] = discovery

    # Parse infrastructure_tools config
    raw_infra = config.get("infrastructure_tools", None)
    if raw_infra is not None:
        if isinstance(raw_infra, list):
            infrastructure_tools: set[str] = set(raw_infra)
        else:
            logger.warning(
                "infrastructure_tools config must be a list, got %s; using default",
                type(raw_infra).__name__,
            )
            infrastructure_tools = {"mode", "todo"}
    else:
        infrastructure_tools = {"mode", "todo"}

    # Create hooks instance
    hooks = ModeHooks(coordinator, discovery, infrastructure_tools=infrastructure_tools)

    # Store hooks in session state for mode switching (to reset warnings)
    coordinator.session_state["mode_hooks"] = hooks

    # Register hooks
    coordinator.hooks.register(
        "provider:request",
        hooks.handle_provider_request,
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

    # Phase 2: register mode-transition handlers that drive RuntimeOverlay
    # apply/revoke on the lifecycle events emitted by tool-mode.
    coordinator.hooks.register(
        "mode:activated",
        hooks.handle_mode_activated,
        name="mode-overlay-activate",
    )
    coordinator.hooks.register(
        "mode:changed",
        hooks.handle_mode_changed,
        name="mode-overlay-change",
    )
    coordinator.hooks.register(
        "mode:cleared",
        hooks.handle_mode_cleared,
        name="mode-overlay-clear",
    )

    # Contribute event catalogue to observability.events channel
    coordinator.register_contributor(
        "observability.events", "bundle-modes:hooks-mode", lambda: ALL_EVENTS
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
    "ModeListing",
    "mount",
    "parse_mode_file",
]
