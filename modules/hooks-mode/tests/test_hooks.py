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


class _InstructionLease:
    """Small v1 lease fake; its callback stays on the ModeHooks object."""

    def __init__(self, route: str = "pending", close_error: Exception | None = None):
        self.route = route
        self.close_error = close_error
        self.closed = False

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _InstructionAssembly:
    """Capture one source registration without importing context-simple at runtime."""

    def __init__(self, lease: _InstructionLease):
        self.lease = lease
        self.registrations: list[tuple[str, object]] = []

    def register(self, source_id: str, callback: object) -> _InstructionLease:
        self.registrations.append((source_id, callback))
        return self.lease


class TestV1InstructionSource:
    """Mode instructions use v1 only when its optional request route is active."""

    @staticmethod
    def _coordinator_with_assembly(
        assembly: _InstructionAssembly, active_mode: str | None = None
    ) -> MagicMock:
        coordinator = _make_coordinator(active_mode)

        def get_capability(name: str):
            if name == "context.instructions.v1":
                return assembly
            return None

        coordinator.get_capability = MagicMock(side_effect=get_capability)
        coordinator.register_contributor = MagicMock()
        return coordinator

    @pytest.mark.asyncio
    async def test_v1_refreshes_current_mode_and_suppresses_legacy_injection(
        self, tmp_path: Path
    ) -> None:
        """A → B → off exposes only the freshly cached record on the v1 route."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "mode-a")
        _create_mode_file(modes_dir, "mode-b")
        lease = _InstructionLease(route="v1")
        assembly = _InstructionAssembly(lease)
        coordinator = self._coordinator_with_assembly(assembly)

        from amplifier_module_hooks_mode import mount

        cleanup = await mount(coordinator, {"search_paths": [str(modes_dir)]})
        assert len(assembly.registrations) == 1
        source_id, callback = assembly.registrations[0]
        assert source_id == "bundle-modes:hooks-mode"
        assert callable(callback)

        coordinator.session_state["active_mode"] = "mode-a"
        first = await coordinator.session_state["mode_hooks"].handle_provider_request(
            "provider:request", {}
        )
        first_records = callback({})
        assert first.action == "continue"
        assert first.context_injection is None
        assert first_records == [
            {
                "key": "current-mode",
                "content": first_records[0]["content"],
                "placement": "before_human",
            }
        ]
        assert "You are in mode-a mode." in first_records[0]["content"]

        # The assembly receives a deep-detached record, not mutable cache state.
        first_records[0]["content"] = "tampered"
        assert "tampered" not in callback({})[0]["content"]

        coordinator.session_state["active_mode"] = "mode-b"
        second = await coordinator.session_state["mode_hooks"].handle_provider_request(
            "provider:request", {}
        )
        second_records = callback({})
        assert second.action == "continue"
        assert "You are in mode-b mode." in second_records[0]["content"]
        assert "mode-a mode" not in second_records[0]["content"]

        coordinator.session_state["active_mode"] = None
        third = await coordinator.session_state["mode_hooks"].handle_provider_request(
            "provider:request", {}
        )
        third_records = callback({})
        assert third.action == "continue"
        assert "No mode is currently active." in third_records[0]["content"]
        assert "mode-b mode" not in third_records[0]["content"]

        await cleanup()
        assert lease.closed

    @pytest.mark.asyncio
    async def test_legacy_route_keeps_hook_result_and_v1_refresh_failure_denies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pending/legacy preserve injection; a v1 refresh never replays stale text."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "v1-plan")
        lease = _InstructionLease(route="legacy")
        assembly = _InstructionAssembly(lease)
        coordinator = self._coordinator_with_assembly(assembly, active_mode="v1-plan")

        from amplifier_module_hooks_mode import mount

        await mount(coordinator, {"search_paths": [str(modes_dir)]})
        hooks = coordinator.session_state["mode_hooks"]
        legacy = await hooks.handle_provider_request("provider:request", {})
        assert legacy.action == "inject_context"
        assert "You are in v1-plan mode." in legacy.context_injection

        lease.route = "v1"
        monkeypatch.setattr(
            hooks, "_get_active_mode", MagicMock(side_effect=RuntimeError("boom"))
        )
        failed = await hooks.handle_provider_request("provider:request", {})
        assert failed.action == "deny"
        assert failed.reason == "mode instruction source refresh failed"

        _source_id, callback = assembly.registrations[0]
        with pytest.raises(RuntimeError, match="mode instruction source refresh failed"):
            callback({})

    @pytest.mark.asyncio
    async def test_v1_source_cleanup_tolerates_an_already_closed_lease(
        self, tmp_path: Path
    ) -> None:
        """Cleanup clears the local lease before attempting its idempotent close."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        lease = _InstructionLease(close_error=RuntimeError("already closed"))
        assembly = _InstructionAssembly(lease)
        coordinator = self._coordinator_with_assembly(assembly)

        from amplifier_module_hooks_mode import mount

        cleanup = await mount(coordinator, {"search_paths": [str(modes_dir)]})
        await cleanup()
        await cleanup()
        assert lease.closed
        assert coordinator.session_state["mode_hooks"]._instruction_lease is None


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
    async def test_warn_first_call_emits_outcome_denied_second_emits_outcome_allowed(
        self, tmp_path: Path
    ) -> None:
        """First warn-list call emits mode:tool_warned (outcome="denied") and denies.
        Second call emits mode:tool_warned (outcome="allowed") and allows.
        One event per decision; outcome discriminates without a positional flag.
        """
        from amplifier_module_hooks_mode.events import MODE_TOOL_WARNED

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        self._make_mode_file(modes_dir, "careful", warn=["bash"])

        coordinator = _make_coordinator(active_mode="careful")
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        # First call: denied with warning, emits MODE_TOOL_WARNED with outcome="denied"
        result1 = await hooks.handle_tool_pre("tool:pre", {"tool_name": "bash"})
        assert result1.action == "deny"
        coordinator.hooks.emit.assert_awaited_once_with(
            MODE_TOOL_WARNED,
            {"tool_name": "bash", "mode": "careful", "outcome": "denied"},
        )

        # Second call: allowed, emits MODE_TOOL_WARNED with outcome="allowed"
        coordinator.hooks.emit.reset_mock()
        result2 = await hooks.handle_tool_pre("tool:pre", {"tool_name": "bash"})
        assert result2.action == "continue"
        coordinator.hooks.emit.assert_awaited_once_with(
            MODE_TOOL_WARNED,
            {"tool_name": "bash", "mode": "careful", "outcome": "allowed"},
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
        """Outer try/except: any exception inside the handler — including a
        (near-impossible) emit raise — is caught and the handler fails closed,
        returning HookResult(action="deny").

        coordinator.hooks.emit() is infallible at the kernel level (hooks.rs:212-222),
        so an emit raise represents a kernel-bug scenario. The outer try/except also
        closes the real gap: handler-logic exceptions (AttributeError, KeyError, etc.)
        that would otherwise let the security decision silently escape.
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
    async def test_no_active_mode_injects_status_reminder(self, tmp_path: Path) -> None:
        """When no active mode, handler should inject mode-status reminder."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()

        coordinator = _make_coordinator(active_mode=None)
        coordinator.hooks.emit = AsyncMock()
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})

        assert result.action == "inject_context"
        assert 'source="mode-status"' in result.context_injection
        assert "No mode is currently active" in result.context_injection
        assert result.ephemeral is True
        coordinator.hooks.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_emit_failure_is_caught_and_continue_returned(
        self, tmp_path: Path
    ) -> None:
        """Outer try/except: any exception inside the handler — including a
        (near-impossible) emit raise — is caught and the handler fails open,
        returning HookResult(action="continue") so a bug never breaks a provider
        request. Context injection is skipped on failure, which is the correct
        fail-open behavior for a non-security-decisioned handler.
        """
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "plan")

        coordinator = _make_coordinator(active_mode="plan")
        coordinator.hooks.emit = AsyncMock(side_effect=RuntimeError("emit failed"))
        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        result = await hooks.handle_provider_request("provider:request", {})
        assert result.action == "continue"


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


# ---------------------------------------------------------------------------
# B3 guard: warn on session-state inconsistency
#
# When active_mode is None but a mode_runtime_overlay exists in session_state,
# it indicates session-resume state loss (in-process session_state was not
# persisted across process restarts).  The guard doesn't fix the bug but
# makes the failure LOUD (logged WARNING) rather than SILENT (no injection
# and no indication why).
# ---------------------------------------------------------------------------


class TestB3SessionStateInconsistencyGuard:
    """Regression guard for B3 (session-resume state loss detection).

    handle_provider_request must log a WARNING when it detects that a
    mode_runtime_overlay exists in session_state but active_mode is None.
    This indicates that the overlay was constructed in a prior process turn
    but the active_mode flag was lost on resume.
    """

    @pytest.mark.asyncio
    async def test_warns_when_overlay_exists_but_active_mode_is_none(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """WARN is emitted when mode_runtime_overlay is set but active_mode is None."""
        import logging

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        _create_mode_file(modes_dir, "design")

        coordinator = _make_coordinator(active_mode=None)
        # Simulate state after session resume: overlay was created in previous
        # process but active_mode was lost (it's in-process memory only)
        coordinator.session_state["mode_runtime_overlay"] = MagicMock()

        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            result = await hooks.handle_provider_request("provider:request", {})

        # Handler should inject the no-mode reminder along with the WARNING
        assert result.action == "inject_context"
        assert 'source="mode-status"' in result.context_injection

        # The WARNING must be logged
        assert any(
            "active_mode is None" in record.message
            and record.levelno == logging.WARNING
            for record in caplog.records
        ), (
            "Expected a WARNING about session-state inconsistency but none was logged. "
            f"Logged messages: {[r.message for r in caplog.records]}"
        )

    @pytest.mark.asyncio
    async def test_no_warn_when_no_overlay_and_no_active_mode(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No WARNING when both active_mode and overlay are absent (normal inactive state)."""
        import logging

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()

        coordinator = _make_coordinator(active_mode=None)
        # No overlay in session_state — this is normal before any mode is activated
        # (session_state["mode_runtime_overlay"] is absent, not just None)

        discovery = ModeDiscovery(search_paths=[modes_dir])
        hooks = ModeHooks(coordinator, discovery)

        with caplog.at_level(logging.WARNING, logger="amplifier_module_hooks_mode"):
            result = await hooks.handle_provider_request("provider:request", {})

        # Should inject the no-mode reminder
        assert result.action == "inject_context"
        assert 'source="mode-status"' in result.context_injection
        # No inconsistency warning should fire when overlay is genuinely absent
        inconsistency_warnings = [
            r
            for r in caplog.records
            if "active_mode is None" in r.message and r.levelno == logging.WARNING
        ]
        assert not inconsistency_warnings, (
            "Unexpected inconsistency WARNING when no overlay exists: "
            f"{[r.message for r in inconsistency_warnings]}"
        )
