"""Tests for ModeHooks and mount() behavior."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks


def _create_mode_file(path: Path, name: str, description: str = "") -> Path:
    """Helper: create a minimal mode .md file with valid YAML frontmatter."""
    mode_file = path / f"{name}.md"
    mode_file.write_text(
        textwrap.dedent(f"""\
            ---
            mode:
              name: {name}
              description: "{description or name + " mode"}"
              tools:
                safe: [read_file, grep]
              default_action: block
            ---
            # {name.title()} Mode
            You are in {name} mode.
        """),
        encoding="utf-8",
    )
    return mode_file


def _make_coordinator(active_mode: str | None = None) -> MagicMock:
    """Create a mock coordinator with session_state.

    coordinator.hooks.emit is an AsyncMock so that bare ``await coordinator.hooks.emit(...)``
    calls (the canonical ecosystem pattern — no per-emit try/except) work without raising
    ``TypeError: object MagicMock can't be used in 'await' expression``.
    """
    coordinator = MagicMock()
    coordinator.session_state = {
        "active_mode": active_mode,
        "require_approval_tools": set(),
    }
    coordinator.hooks = MagicMock()
    coordinator.hooks.emit = AsyncMock()
    coordinator.get_capability = MagicMock(return_value=None)
    return coordinator


class TestMountEventRegistration:
    """Fix 1: mount() must register context injection on provider:request."""

    @pytest.mark.asyncio
    async def test_mount_registers_on_provider_request(self, tmp_path: Path) -> None:
        """The context injection handler must be registered on 'provider:request',
        NOT 'prompt:submit'."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")

        coordinator = _make_coordinator()

        from amplifier_module_hooks_mode import mount

        await mount(coordinator, {"search_paths": [str(modes_dir)]})

        register_calls = coordinator.hooks.register.call_args_list

        context_registration = None
        for c in register_calls:
            args, kwargs = c
            if kwargs.get("name") == "mode-context":
                context_registration = c
                break

        assert context_registration is not None, (
            "Expected a hooks.register call with name='mode-context'"
        )

        args, kwargs = context_registration
        event_name = args[0]
        assert event_name == "provider:request", (
            f"mode-context handler must be registered on 'provider:request', "
            f"but was registered on '{event_name}'"
        )


class TestHandlerMethodName:
    """Fix 1: The handler method should be named handle_provider_request."""

    def test_mode_hooks_has_handle_provider_request(self) -> None:
        """ModeHooks must have handle_provider_request method."""
        assert hasattr(ModeHooks, "handle_provider_request"), (
            "ModeHooks must have a 'handle_provider_request' method"
        )

    def test_mode_hooks_no_handle_prompt_submit(self) -> None:
        """The old handle_prompt_submit method must not exist."""
        assert not hasattr(ModeHooks, "handle_prompt_submit"), (
            "ModeHooks must NOT have the old 'handle_prompt_submit' method -- "
            "it should be renamed to 'handle_provider_request'"
        )


class TestInfrastructureToolsBypass:
    """Fix 2: Infrastructure tools must bypass the mode tool cascade."""

    @pytest.mark.asyncio
    async def test_mode_tool_allowed_by_default(self, tmp_path: Path) -> None:
        """The 'mode' tool must be allowed even when default_action is 'block'
        and 'mode' is not in safe_tools."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "strict")

        coordinator = _make_coordinator(active_mode="strict")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "mode"})
        assert result.action == "continue", (
            f"'mode' tool must be allowed (infrastructure tool), "
            f"but got action='{result.action}'"
        )

    @pytest.mark.asyncio
    async def test_todo_tool_allowed_by_default(self, tmp_path: Path) -> None:
        """The 'todo' tool must be allowed even when default_action is 'block'
        and 'todo' is not in safe_tools."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "notodo")

        coordinator = _make_coordinator(active_mode="notodo")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "todo"})
        assert result.action == "continue", (
            f"'todo' tool must be allowed (infrastructure tool), "
            f"but got action='{result.action}'"
        )

    @pytest.mark.asyncio
    async def test_non_infrastructure_tool_still_blocked(self, tmp_path: Path) -> None:
        """Tools NOT in infrastructure_tools must still follow the cascade."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "strict")

        coordinator = _make_coordinator(active_mode="strict")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "write_file"})
        assert result.action == "deny", (
            f"'write_file' must still be blocked by default_action, "
            f"but got action='{result.action}'"
        )


class TestInfrastructureToolsConfig:
    """Fix 2: infrastructure_tools must be configurable."""

    @pytest.mark.asyncio
    async def test_custom_infrastructure_tools(self, tmp_path: Path) -> None:
        """When infrastructure_tools is set to a custom list, only those tools bypass."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "custom")

        coordinator = _make_coordinator(active_mode="custom")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery, infrastructure_tools={"mode"})

        # "mode" should still be allowed
        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "mode"})
        assert result.action == "continue"

        # "todo" should now be blocked (not in custom list)
        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "todo"})
        assert result.action == "deny"

    @pytest.mark.asyncio
    async def test_empty_infrastructure_tools_blocks_mode(self, tmp_path: Path) -> None:
        """When infrastructure_tools is empty, even the mode tool is blocked."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "locked")

        coordinator = _make_coordinator(active_mode="locked")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery, infrastructure_tools=set())

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "mode"})
        assert result.action == "deny", (
            "With empty infrastructure_tools, 'mode' must be blocked"
        )


class TestModeActiveSignal:
    """Fix 3: Context injection must include an explicit MODE ACTIVE banner."""

    @pytest.mark.asyncio
    async def test_context_has_mode_active_banner(self, tmp_path: Path) -> None:
        """Injected context must start with 'MODE ACTIVE: {name}' inside the tags."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        coordinator = _make_coordinator(active_mode="plan")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "inject_context"
        content = result.context_injection
        assert "MODE ACTIVE: plan" in content

    @pytest.mark.asyncio
    async def test_context_has_do_not_reactivate_warning(self, tmp_path: Path) -> None:
        """Injected context must warn the agent not to re-activate the current mode."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "brainstorm", "Brainstorm mode")

        coordinator = _make_coordinator(active_mode="brainstorm")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})
        content = result.context_injection
        assert "do NOT call" in content or "do not call" in content.lower()
        assert "brainstorm" in content

    @pytest.mark.asyncio
    async def test_context_still_contains_mode_content(self, tmp_path: Path) -> None:
        """The mode's markdown body must still be included after the banner."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        coordinator = _make_coordinator(active_mode="plan")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})
        content = result.context_injection
        assert "You are in plan mode." in content

    @pytest.mark.asyncio
    async def test_context_wrapped_in_system_reminder_tags(
        self, tmp_path: Path
    ) -> None:
        """Context must be wrapped in <system-reminder> tags with mode source."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan", "Plan mode")

        coordinator = _make_coordinator(active_mode="plan")
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})
        content = result.context_injection
        assert content.startswith('<system-reminder source="mode-plan">')
        assert content.rstrip().endswith("</system-reminder>")


class TestLastContextHashAttribute:
    """task-2: ModeHooks must have a _last_context_hash attribute."""

    def test_initial_hash_is_none(self, tmp_path: Path) -> None:
        """_last_context_hash must be None after construction."""
        coordinator = _make_coordinator()
        discovery = ModeDiscovery(search_paths=[tmp_path])
        hooks = ModeHooks(coordinator, discovery)
        assert hooks._last_context_hash is None

    def test_reset_warnings_resets_last_context_hash(self, tmp_path: Path) -> None:
        """reset_warnings() must reset _last_context_hash to None."""
        coordinator = _make_coordinator()
        discovery = ModeDiscovery(search_paths=[tmp_path])
        hooks = ModeHooks(coordinator, discovery)
        hooks._last_context_hash = "deadbeef"
        hooks.reset_warnings()
        assert hooks._last_context_hash is None


class TestToolEnforcementEvents:
    """task-3: handle_tool_pre must emit mode:tool_blocked and mode:tool_warned."""

    def _make_mode_file(
        self,
        path: Path,
        name: str,
        *,
        block: list[str] | None = None,
        warn: list[str] | None = None,
        safe: list[str] | None = None,
        default_action: str = "block",
    ) -> None:
        """Write a mode file with given tool policies."""
        block_list = ", ".join(f'"{t}"' for t in (block or []))
        warn_list = ", ".join(f'"{t}"' for t in (warn or []))
        safe_list = ", ".join(f'"{t}"' for t in (safe or ["read_file"]))
        (path / f"{name}.md").write_text(
            textwrap.dedent(f"""\
                ---
                mode:
                  name: {name}
                  description: "{name} mode"
                  tools:
                    safe: [{safe_list}]
                    warn: [{warn_list}]
                    block: [{block_list}]
                  default_action: {default_action}
                ---
                # {name.title()} Mode
                You are in {name} mode.
            """),
            encoding="utf-8",
        )

    @pytest.mark.asyncio
    async def test_block_list_emits_tool_blocked(self, tmp_path: Path) -> None:
        """block_list tool triggers mode:tool_blocked with reason='block_list'."""
        from amplifier_module_hooks_mode.events import MODE_TOOL_BLOCKED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        self._make_mode_file(modes_dir, "strict", block=["bash"])

        coordinator = _make_coordinator(active_mode="strict")
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "bash"})

        assert result.action == "deny"
        coordinator.hooks.emit.assert_awaited_once_with(
            MODE_TOOL_BLOCKED,
            {"tool_name": "bash", "mode": "strict", "reason": "block_list"},
        )

    @pytest.mark.asyncio
    async def test_default_action_block_emits_tool_blocked(
        self, tmp_path: Path
    ) -> None:
        """Unlisted tool with default_action=block emits mode:tool_blocked with reason='default_action'."""
        from amplifier_module_hooks_mode.events import MODE_TOOL_BLOCKED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        self._make_mode_file(modes_dir, "plan", default_action="block")

        coordinator = _make_coordinator(active_mode="plan")
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "write_file"})

        assert result.action == "deny"
        coordinator.hooks.emit.assert_awaited_once_with(
            MODE_TOOL_BLOCKED,
            {"tool_name": "write_file", "mode": "plan", "reason": "default_action"},
        )

    @pytest.mark.asyncio
    async def test_warn_first_call_emits_is_first_true_second_emits_is_first_false(
        self, tmp_path: Path
    ) -> None:
        """First warn-list call emits mode:tool_warned (is_first_warning=True) and denies.
        Second call emits mode:tool_warned (is_first_warning=False) and allows.
        This lets observers distinguish "warned and denied" from "warned then allowed."
        """
        from amplifier_module_hooks_mode.events import MODE_TOOL_WARNED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        self._make_mode_file(modes_dir, "careful", warn=["bash"])

        coordinator = _make_coordinator(active_mode="careful")
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        # First call: denied with warning, emits MODE_TOOL_WARNED with is_first_warning=True
        result1 = await hooks.handle_tool_pre("tool:pre", {"tool_name": "bash"})
        assert result1.action == "deny"
        coordinator.hooks.emit.assert_awaited_once_with(
            MODE_TOOL_WARNED,
            {"tool_name": "bash", "mode": "careful", "is_first_warning": True},
        )

        # Second call: allowed, emits MODE_TOOL_WARNED with is_first_warning=False
        coordinator.hooks.emit.reset_mock()
        result2 = await hooks.handle_tool_pre("tool:pre", {"tool_name": "bash"})
        assert result2.action == "continue"
        coordinator.hooks.emit.assert_awaited_once_with(
            MODE_TOOL_WARNED,
            {"tool_name": "bash", "mode": "careful", "is_first_warning": False},
        )

    @pytest.mark.asyncio
    async def test_safe_tool_emits_no_event(self, tmp_path: Path) -> None:
        """Safe tool bypasses all emit paths; no event emitted."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        self._make_mode_file(modes_dir, "plan", safe=["read_file"])

        coordinator = _make_coordinator(active_mode="plan")
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "read_file"})

        assert result.action == "continue"
        coordinator.hooks.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_emit_failure_is_caught_and_deny_returned(
        self, tmp_path: Path
    ) -> None:
        """Per-emit try/except: a RuntimeError from emit is caught and the deny
        HookResult is returned anyway.

        hooks-mode uses fail-open observability, fail-closed security: the
        HookResult is computed before the emit, and if the emit raises the result
        is returned regardless. This guarantees HookResult delivery to the kernel
        even when the bridge/serialization layer fails.
        """
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        self._make_mode_file(modes_dir, "strict", block=["bash"])

        coordinator = _make_coordinator(active_mode="strict")
        coordinator.hooks.emit = AsyncMock(side_effect=RuntimeError("emit failed"))
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_tool_pre("tool:pre", {"tool_name": "bash"})
        assert result.action == "deny"


class TestContextInjectedEvent:
    """task-4: handle_provider_request must emit mode:context_injected (hash-gated)."""

    @pytest.mark.asyncio
    async def test_first_call_emits_context_injected(self, tmp_path: Path) -> None:
        """First call emits mode:context_injected with correct payload and sets _last_context_hash."""
        import hashlib

        from amplifier_module_hooks_mode.events import MODE_CONTEXT_INJECTED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")

        coordinator = _make_coordinator(active_mode="plan")
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        # Load mode_def to get expected context
        mode_def = discovery.find("plan")
        assert mode_def is not None
        expected_hash = hashlib.sha256(mode_def.context.encode()).hexdigest()
        expected_length = len(mode_def.context)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "inject_context"
        coordinator.hooks.emit.assert_awaited_once_with(
            MODE_CONTEXT_INJECTED,
            {
                "mode": "plan",
                "context_length": expected_length,
                "content_hash": expected_hash,
            },
        )
        assert hooks._last_context_hash == expected_hash

    @pytest.mark.asyncio
    async def test_second_call_same_context_does_not_emit(self, tmp_path: Path) -> None:
        """Second call with same context does NOT emit again (call_count stays at 1)."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")

        coordinator = _make_coordinator(active_mode="plan")
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        # First call — emits
        await hooks.handle_provider_request("provider:request", {})
        assert coordinator.hooks.emit.await_count == 1

        # Second call with same context — must NOT emit again
        await hooks.handle_provider_request("provider:request", {})
        assert coordinator.hooks.emit.await_count == 1, (
            "emit should not be called again when context hash has not changed"
        )

    @pytest.mark.asyncio
    async def test_reset_warnings_causes_re_emission(self, tmp_path: Path) -> None:
        """After reset_warnings(), the next call emits mode:context_injected again."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")

        coordinator = _make_coordinator(active_mode="plan")
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        # First call — emits (count=1)
        await hooks.handle_provider_request("provider:request", {})
        assert coordinator.hooks.emit.await_count == 1

        # Reset warnings clears the hash
        hooks.reset_warnings()
        assert hooks._last_context_hash is None

        # Next call should emit again (count=2)
        await hooks.handle_provider_request("provider:request", {})
        assert coordinator.hooks.emit.await_count == 2, (
            "emit should be called again after reset_warnings() clears the hash"
        )

    @pytest.mark.asyncio
    async def test_no_active_mode_does_not_emit(self, tmp_path: Path) -> None:
        """When no active mode, emit is not called and result.action == 'continue'."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()

        coordinator = _make_coordinator(active_mode=None)
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "continue"
        coordinator.hooks.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_emit_failure_is_caught_and_inject_context_returned(
        self, tmp_path: Path
    ) -> None:
        """Per-emit try/except: a RuntimeError from emit is caught and the
        inject_context HookResult is returned anyway.

        Context injection is fail-open for observability: if the mode:context_injected
        emit raises, the warning is logged and context is still injected into the
        provider request. The emit failure never disrupts the primary hook function.
        """
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")

        coordinator = _make_coordinator(active_mode="plan")
        coordinator.hooks.emit = AsyncMock(side_effect=RuntimeError("emit failed"))
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})
        assert result.action == "inject_context"


class TestEventsContributorRegistration:
    """task-5: mount() must register observability.events contributor."""

    @pytest.mark.asyncio
    async def test_mount_registers_observability_events_contributor(
        self, tmp_path: Path
    ) -> None:
        """mount() registers a contributor with channel='observability.events',
        id='bundle-modes:hooks-mode', and supplier returning ALL_EVENTS."""
        from amplifier_module_hooks_mode import mount
        from amplifier_module_hooks_mode.events import ALL_EVENTS

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")

        coordinator = _make_coordinator()
        coordinator.register_contributor = MagicMock()

        await mount(coordinator, {"search_paths": [str(modes_dir)]})

        # Find the call with 'observability.events' as first arg
        contributor_call = None
        for call in coordinator.register_contributor.call_args_list:
            args, kwargs = call
            if args and args[0] == "observability.events":
                contributor_call = call
                break

        assert contributor_call is not None, (
            "Expected coordinator.register_contributor to be called with 'observability.events'"
        )

        args, kwargs = contributor_call
        channel = args[0]
        contributor_id = args[1]
        supplier = args[2]

        assert channel == "observability.events"
        assert contributor_id == "bundle-modes:hooks-mode"
        assert supplier() == ALL_EVENTS
