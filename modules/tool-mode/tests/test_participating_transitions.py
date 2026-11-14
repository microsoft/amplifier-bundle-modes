"""Actual ModeTool + hooks-mode on Core, using public issuer operations only.

Synthetic component integration, not an installed-host/provider qualification.
Foundation is supplied by the test host, not a new modes runtime dependency.
"""

import asyncio
import logging
import sys
from contextlib import contextmanager
from copy import deepcopy
from importlib.metadata import version
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from amplifier_core import AmplifierSession, HookResult
from amplifier_foundation import RUNTIME_CONTEXT_OVERLAY_CAPABILITY
from amplifier_foundation.session.media_hook_bridge import install_media_hook_bridge
from amplifier_module_hooks_mode import mount as mount_hooks
from amplifier_module_tool_mode import GRAPH_TRANSITION_CAPABILITY, mount as mount_tool


pytestmark = pytest.mark.skipif(
    version("amplifier-core") != "2.0.2",
    reason="Participating component fixture requires actual Core 2.0.2",
)


class Loader:
    """Configured real modules, plus inert context/orchestrator endpoints."""

    def __init__(self):
        self.queue = []

    async def load(self, module_id, config, *, source_hint=None, coordinator=None):
        async def mount(current, config=None):
            await current.mount(
                "orchestrator" if module_id == "fixture-loop" else "context", object()
            )

        if module_id in {"hooks-mode", "tool-mode"}:
            async def mount(current):
                factory = mount_hooks if module_id == "hooks-mode" else mount_tool
                return await factory(current, config)

        return mount

    def enqueue_on_session_ready(self, name, callback):
        self.queue.append((name, callback))

    def get_on_session_ready_queue(self):
        return self.queue

    def clear_on_session_ready_queue(self):
        self.queue.clear()


@pytest_asyncio.fixture
async def runtime(tmp_path):
    for name in ("alpha", "beta"):
        (tmp_path / f"{name}.md").write_text(
            f"---\nmode:\n  name: {name}\n  description: {name}\n"
            f"  contributes:\n    context: ['{name}.txt']\n---\n{name}\n"
        )
    session = AmplifierSession(
        {
            "session": {"orchestrator": "fixture-loop", "context": "fixture-context"},
            "hooks": [{"module": "hooks-mode", "config": {"search_paths": [str(tmp_path)]}}],
            "tools": [{"module": "tool-mode", "config": {"gate_policy": "auto"}}],
        },
        session_id="actual-mode-component",
    )
    session.coordinator.loader = Loader()
    bridge = install_media_hook_bridge(session.coordinator)
    graph = bridge.begin_participating_graph(
        session,
        owner="modes.component.core2",
        participants=("fixture-loop", "fixture-context", "hooks-mode", "tool-mode", "host.mode"),
    )
    await session.initialize()
    calls = []
    host = graph.participant("host.mode")

    async def contributor(event, data):
        calls.append((event, deepcopy(data)))
        # A real secondary contributor changes configuration and the callback
        # graph during the same operation, not just captured mount views.
        host.config["mode_component"] = event
        if event == "mode:activated":
            host.hooks.register("tool:post", lambda e, d: HookResult(), name="mode-added")

    for event in ("mode:activated", "mode:changed", "mode:cleared"):
        host.hooks.register(event, contributor, name=f"secondary-{event}")
    graph.seal()
    state = SimpleNamespace(
        session=session, bridge=bridge, graph=graph, calls=calls, entries=0, exit_error=None
    )

    @contextmanager
    def transition():
        with state.graph.transition() as successor:
            state.graph = successor
            state.entries += 1
            yield
            if state.exit_error:
                raise state.exit_error

    session.coordinator.register_capability(GRAPH_TRANSITION_CAPABILITY, transition)
    state.tool = session.coordinator.get("tools", "mode")
    state.hooks = session.coordinator.session_state["mode_hooks"]
    try:
        yield state
    finally:
        await session.cleanup()


async def change(runtime, operation="set", name="alpha"):
    return await runtime.tool.execute({"operation": operation, "name": name})


@pytest.mark.asyncio
async def test_actual_set_change_clear_new_issuer_generations(runtime):
    for operation, name, active, context in (
        ("set", "alpha", "alpha", ["alpha.txt"]),
        ("set", "beta", "beta", ["beta.txt"]),
        ("clear", None, None, []),
    ):
        old = runtime.bridge.graph_receipt
        assert runtime.bridge.validate_receipt(old)
        result = await change(runtime, operation, name)
        assert result.success, result.error
        new = runtime.bridge.graph_receipt
        assert new is not old
        assert not runtime.bridge.validate_receipt(old)
        assert runtime.bridge.validate_receipt(new)
        coord = runtime.session.coordinator
        assert coord.session_state["active_mode"] == active
        assert coord.get_capability(RUNTIME_CONTEXT_OVERLAY_CAPABILITY) == context
    assert runtime.entries == 3
    assert [event for event, _ in runtime.calls] == [
        "mode:activated", "mode:changed", "mode:cleared"
    ]
    assert all(isinstance(data["transition_id"], str) for _, data in runtime.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["set", "clear"])
async def test_counted_candidate_refuses_before_actual_events_or_changes(runtime, operation):
    if operation == "clear":
        assert (await change(runtime)).success
    coord = runtime.session.coordinator
    before = deepcopy(coord.config)
    mode = coord.session_state["active_mode"]
    calls, entries = len(runtime.calls), runtime.entries
    old = runtime.bridge.graph_receipt
    # Public counted request lifetime: no private flags or force sealing.
    with runtime.bridge.request_scope() as validate:
        assert validate()
        result = await change(runtime, operation, "beta")
        assert not result.success
        assert validate()
    assert coord.config == before
    assert coord.session_state["active_mode"] == mode
    assert len(runtime.calls) == calls and runtime.entries == entries
    assert runtime.bridge.validate_receipt(old)
    assert "mode_transition_failure" not in coord.session_state


@pytest.mark.asyncio
async def test_warn_confirm_and_ordinary_refusals_do_not_open_transition(runtime):
    tool = runtime.tool
    tool.gate_policy = "warn"
    assert not (await change(runtime)).success
    assert runtime.entries == 0
    assert (await change(runtime)).success
    assert runtime.entries == 1
    tool.gate_policy = "confirm"
    assert not (await change(runtime, "clear")).success
    assert not (await change(runtime, name="beta")).success
    assert runtime.entries == 1
    tool.gate_policy = "auto"
    definition = runtime.hooks.discovery.find("alpha")
    definition.allowed_transitions = []
    definition.allow_clear = False
    assert not (await change(runtime, name="beta")).success
    assert not (await change(runtime, "clear")).success
    assert runtime.entries == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("factory", [False, "not-callable", lambda: object()])
async def test_present_malformed_factory_never_falls_back(runtime, factory):
    runtime.session.coordinator.register_capability(GRAPH_TRANSITION_CAPABILITY, factory)
    old = runtime.bridge.graph_receipt
    assert not (await change(runtime)).success
    assert runtime.calls == [] and runtime.entries == 0
    assert runtime.session.coordinator.session_state["active_mode"] is None
    assert runtime.bridge.validate_receipt(old)


@pytest.mark.asyncio
async def test_no_capability_actual_native_lane_unchanged(runtime):
    # A fresh actual native session, not a participant graph stripped of its
    # capability and then requalified by a test.
    session = AmplifierSession(
        {"session": {"orchestrator": "fixture-loop", "context": "fixture-context"}}
    )
    coord = session.coordinator
    await mount_hooks(coord)
    coord.session_state["mode_discovery"] = runtime.hooks.discovery
    coord.session_state["mode_hooks"].discovery = runtime.hooks.discovery
    await mount_tool(coord, {"gate_policy": "auto"})
    tool = coord.get("tools", "mode")
    assert coord.get_capability(GRAPH_TRANSITION_CAPABILITY) is None
    assert (await tool.execute({"operation": "set", "name": "alpha"})).success
    assert coord.session_state["active_mode"] == "alpha"
    assert coord.get_capability(RUNTIME_CONTEXT_OVERLAY_CAPABILITY) == ["alpha.txt"]
    assert (await tool.execute({"operation": "clear"})).success
    assert coord.session_state["active_mode"] is None
    await session.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["activate", "change", "clear"])
@pytest.mark.parametrize("failure", ["false", "exception", "cancel"])
async def test_internal_contributor_failure_crosses_host_boundary(runtime, phase, failure):
    if phase != "activate":
        assert (await change(runtime)).success
    old = runtime.bridge.graph_receipt
    overlay = runtime.hooks._get_or_create_overlay()
    method = "revoke" if phase == "clear" else "apply"
    outcome = SimpleNamespace(success=False, error="controlled contribution refusal")
    error = RuntimeError("controlled contribution exception")
    if failure == "cancel":
        error = asyncio.CancelledError()
    fake = AsyncMock(return_value=outcome) if failure == "false" else AsyncMock(side_effect=error)
    setattr(overlay, method, fake)
    operation, name = ("clear", None) if phase == "clear" else ("set", "beta")
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await change(runtime, operation, name)
    else:
        assert not (await change(runtime, operation, name)).success
    assert not runtime.bridge.validate_receipt(old)
    assert not runtime.bridge.validate_receipt(runtime.bridge.graph_receipt)
    state = runtime.session.coordinator.session_state
    assert state["mode_transition_failure"]["target_mode"] == name
    assert state["mode_runtime_overlay"] is overlay  # retained failure evidence
    assert not (await change(runtime)).success  # no automatic recovery/replay
    assert not (await change(runtime, "current")).success
    listing = await change(runtime, "list")
    assert not listing.success and listing.output["active_mode"] is None
    moderation = await runtime.hooks.handle_tool_pre("tool:pre", {"tool_name": "bash"})
    assert moderation.action == "deny"
    reminder = await runtime.hooks.handle_provider_request("provider:request", {})
    assert "may be partial" in reminder.context_injection


@pytest.mark.asyncio
async def test_missing_callback_never_qualifies_and_trackers_do_not_leak(runtime):
    # Missing actual callback cannot consume an earlier successful acknowledgement.
    assert (await change(runtime)).success
    with runtime.graph.transition() as successor:
        runtime.graph = successor
        successor.participant("hooks-mode").hooks.unregister("mode-overlay-change")
    assert not (await change(runtime, name="beta")).success
    assert not runtime.bridge.validate_receipt(runtime.bridge.graph_receipt)


@pytest.mark.asyncio
async def test_change_revoke_failure_does_not_apply_target(runtime):
    assert (await change(runtime)).success
    overlay = runtime.hooks._get_or_create_overlay()
    overlay.revoke = AsyncMock(return_value=SimpleNamespace(success=False, error="refusal"))
    overlay.apply = AsyncMock()
    assert not (await change(runtime, name="beta")).success
    overlay.apply.assert_not_called()
    assert not runtime.bridge.validate_receipt(runtime.bridge.graph_receipt)


@pytest.mark.asyncio
async def test_missing_tracker_refuses_before_host_entry(runtime):
    runtime.hooks.track_transition = None
    assert not (await change(runtime)).success
    assert runtime.entries == 0 and runtime.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["duplicate", "mismatch", "stale"])
async def test_operation_tracker_rejects_nonmatching_completion(runtime, kind):
    hooks = runtime.hooks
    event = "mode:activated"
    payload = {"name": "alpha"}
    with hooks.track_transition(event, payload=payload) as operation:
        payload["transition_id"] = operation.id
        if kind == "duplicate":
            await hooks.handle_mode_activated(event, payload)
            with pytest.raises(RuntimeError, match="duplicate"):
                await hooks.handle_mode_activated(event, payload)
            with pytest.raises(RuntimeError, match="duplicate"):
                operation.verify()
        elif kind == "mismatch":
            with pytest.raises(RuntimeError, match="Mismatched"):
                await hooks.handle_mode_changed("mode:changed", payload)
            with pytest.raises(RuntimeError, match="Mismatched"):
                operation.verify()
    if kind == "stale":
        with pytest.raises(RuntimeError, match="expired"):
            await hooks.handle_mode_activated(event, payload)
        with hooks.track_transition(event, payload=payload) as next_operation:
            assert next_operation.id != operation.id
            with pytest.raises(RuntimeError, match="did not complete"):
                next_operation.verify()


@pytest.mark.asyncio
async def test_failure_latch_survives_capability_removal(runtime):
    runtime.exit_error = RuntimeError("controlled failure")
    assert not (await change(runtime)).success
    calls = len(runtime.calls)
    runtime.session.coordinator.register_capability(GRAPH_TRANSITION_CAPABILITY, None)
    assert not (await change(runtime, name="beta")).success
    assert len(runtime.calls) == calls  # never downgrade to unguarded native retry


@pytest.mark.asyncio
async def test_completion_is_bound_to_original_mode_target(runtime):
    with runtime.hooks.track_transition(
        "mode:activated", payload={"name": "alpha"}
    ) as operation:
        with pytest.raises(RuntimeError, match="target does not match"):
            await runtime.hooks.handle_mode_activated(
                "mode:activated", {"name": "beta", "transition_id": operation.id}
            )
        with pytest.raises(RuntimeError, match="target does not match"):
            operation.verify()
    assert runtime.session.coordinator.get_capability(RUNTIME_CONTEXT_OVERLAY_CAPABILITY) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["activate", "change", "clear"])
async def test_modified_event_cannot_retarget_the_gated_operation(runtime, phase):
    if phase != "activate":
        assert (await change(runtime)).success
    event = {
        "activate": "mode:activated", "change": "mode:changed", "clear": "mode:cleared"
    }[phase]

    def rewrite(event, data):
        fields = {"old": "beta", "from_mode": "beta"} if phase == "change" else {
            "name": "beta",
            **({"mode": "beta"} if phase == "activate" else {"previous_mode": "beta"}),
        }
        return HookResult(action="modify", data={**data, **fields})

    with runtime.graph.transition() as successor:
        runtime.graph = successor
        successor.participant("host.mode").hooks.register(
            event, rewrite, priority=-50, name="rewrite-gated-mode"
        )
    old = runtime.bridge.graph_receipt
    operation, target = ("clear", None) if phase == "clear" else ("set", "beta" if phase == "change" else "alpha")
    assert not (await change(runtime, operation, target)).success
    assert not runtime.bridge.validate_receipt(old)
    assert not runtime.bridge.validate_receipt(runtime.bridge.graph_receipt)
    contexts = runtime.session.coordinator.get_capability(RUNTIME_CONTEXT_OVERLAY_CAPABILITY)
    assert contexts == (None if phase == "activate" else ["alpha.txt"])


@pytest.mark.asyncio
async def test_primary_cancel_survives_host_exit_error(runtime):
    overlay = runtime.hooks._get_or_create_overlay()
    overlay.apply = AsyncMock(side_effect=asyncio.CancelledError())

    @contextmanager
    def broken_exit():
        try:
            with runtime.graph.transition() as successor:
                runtime.graph = successor
                yield
        finally:
            raise RuntimeError("secondary cleanup error")

    runtime.session.coordinator.register_capability(GRAPH_TRANSITION_CAPABILITY, broken_exit)
    with pytest.raises(asyncio.CancelledError):
        await change(runtime)
    assert not runtime.bridge.validate_receipt(runtime.bridge.graph_receipt)
    assert runtime.hooks._transitions == {}


@pytest.mark.asyncio
async def test_exit_failure_never_reports_success_or_revives_previous_receipt(runtime):
    old = runtime.bridge.graph_receipt
    runtime.exit_error = RuntimeError("host exit failure")
    assert not (await change(runtime)).success
    assert not runtime.bridge.validate_receipt(old)
    assert not runtime.bridge.validate_receipt(runtime.bridge.graph_receipt)
    assert runtime.session.coordinator.session_state["active_mode"] is None
    assert runtime.session.coordinator.session_state["mode_transition_failure"]


@pytest.mark.asyncio
async def test_external_contributor_exception_is_issuer_failure(runtime):
    # Requires the issuer callback witness, separately from the modes tracker.
    def broken(event, data):
        raise RuntimeError("external contributor failed")

    with runtime.graph.transition() as successor:
        runtime.graph = successor
        successor.participant("host.mode").hooks.register(
            "mode:activated", broken, priority=50, name="external-broken"
        )
    old = runtime.bridge.graph_receipt
    result = await change(runtime)
    assert not result.success
    assert not runtime.bridge.validate_receipt(old)
    assert not runtime.bridge.validate_receipt(runtime.bridge.graph_receipt)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["activate", "change", "change_revoke", "clear"])
@pytest.mark.parametrize("failure", ["exception", "cancel", "false"])
@pytest.mark.parametrize("notification", ["normal", "exception", "cancel"])
async def test_participating_failure_diagnostics_are_safe_at_entry(
    runtime, monkeypatch, caplog, phase, failure, notification
):
    """Observe BEFORE logger formatting/filtering and BEFORE native event emit.

    Only new participating Modes diagnostics are qualified, not arbitrary
    contributor/Foundation diagnostics or universal payload sanitization.
    """
    if phase != "activate":
        assert (await change(runtime)).success
    secret = "PRIVATE-MODE-IMAGE-data:image/png;base64,c2VjcmV0-https://private/?token=secret"
    original_error = (
        asyncio.CancelledError(secret) if failure == "cancel" else RuntimeError(secret)
    )
    original_error.__cause__ = ValueError(secret + "-cause")
    original_error.add_note(secret + "-note")
    overlay = runtime.hooks._get_or_create_overlay()
    method = "revoke" if phase in {"clear", "change_revoke"} else "apply"
    setattr(
        overlay, method,
        AsyncMock(return_value=SimpleNamespace(success=False, error=secret))
        if failure == "false" else AsyncMock(side_effect=original_error),
    )
    events, logs, tracked, observed_errors = [], [], [], []
    original_tracker = runtime.hooks.track_transition

    @contextmanager
    def tracker(*args, **kwargs):
        with original_tracker(*args, **kwargs) as operation:
            tracked.append(operation)
            yield operation

    monkeypatch.setattr(runtime.hooks, "track_transition", tracker)
    hooks_type = type(runtime.tool.coordinator.hooks)
    original_emit = hooks_type.emit

    async def emit(self, event, data):
        events.append((event, deepcopy(data)))
        if event == "mode:activation_failed":
            if notification == "exception":
                raise RuntimeError(secret + "-notification")
            if notification == "cancel":
                raise asyncio.CancelledError(secret + "-notification")
        return await original_emit(self, event, data)

    monkeypatch.setattr(hooks_type, "emit", emit)

    def log_entry(self, level, msg, args, **kwargs):
        # At logging's raw entry, before getMessage(), filters or formatters.
        info = kwargs.get("exc_info")
        if info is True:
            info = sys.exc_info()
        logs.append((self.name, level, msg, args, {**kwargs, "exc_info": info}))

    monkeypatch.setattr(logging.Logger, "_log", log_entry)
    original_factory = runtime.session.coordinator.get_capability(GRAPH_TRANSITION_CAPABILITY)

    @contextmanager
    def transition():
        try:
            with original_factory():
                yield
        except BaseException as exc:
            observed_errors.append(exc)
            raise

    runtime.session.coordinator.register_capability(GRAPH_TRANSITION_CAPABILITY, transition)
    operation, target = ("clear", None) if phase == "clear" else ("set", "beta")
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError) as raised:
            await change(runtime, operation, target)
        assert raised.value is original_error
    else:
        assert not (await change(runtime, operation, target)).success
    assert secret not in repr(events)
    assert secret not in repr(logs)
    # Rust's tracing bridge can enter Python logging below Logger._log.
    assert secret not in repr([record.__dict__ for record in caplog.records])
    assert all(not entry[-1].get("exc_info") and not entry[-1].get("stack_info") for entry in logs)
    assert len(tracked) == 1 and tracked[0].error is observed_errors[0]
    if failure != "false":
        assert tracked[0].error is original_error
    assert runtime.session.coordinator.session_state["mode_transition_failure"]
    assert not runtime.bridge.validate_receipt(runtime.bridge.graph_receipt)


@pytest.mark.asyncio
async def test_tracked_failure_never_formats_exception_or_reads_result_error(runtime, monkeypatch):
    class PrivateError(Exception):
        def __str__(self):
            pytest.fail("participating diagnostics called exception.__str__")

        def __repr__(self):
            pytest.fail("participating diagnostics called exception.__repr__")

    class Refused:
        success = False

        @property
        def error(self):
            pytest.fail("participating diagnostics inspected opaque result.error")

    overlay = runtime.hooks._get_or_create_overlay()
    original = PrivateError()
    overlay.apply = AsyncMock(side_effect=original)
    payload = {"name": "alpha"}
    with runtime.hooks.track_transition("mode:activated", payload=payload) as operation:
        hook_result = await runtime.hooks.handle_mode_activated(
            "mode:activated", {**payload, "transition_id": operation.id}
        )
        assert hook_result.action == "continue"  # never hand original to Core's logger
        with pytest.raises(PrivateError) as raised:
            operation.verify()
        assert raised.value is original
    overlay.apply = AsyncMock(return_value=Refused())
    with runtime.hooks.track_transition("mode:activated", payload=payload) as operation:
        await runtime.hooks.handle_mode_activated(
            "mode:activated", {**payload, "transition_id": operation.id}
        )
        with pytest.raises(RuntimeError, match="Mode contribution apply failed"):
            operation.verify()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["set", "clear"])
@pytest.mark.parametrize("boundary", ["enter", "exit"])
async def test_host_failure_diagnostic_is_bounded_before_formatting(
    runtime, monkeypatch, operation, boundary
):
    if operation == "clear":
        assert (await change(runtime)).success
    secret = "PRIVATE-HOST-EXCEPTION-https://secret-image/?token=private"
    entries = []
    primary = RuntimeError(secret)
    primary.add_note(secret)

    @contextmanager
    def factory():
        if boundary == "enter":
            raise primary
        with runtime.graph.transition() as successor:
            runtime.graph = successor
            yield
            raise primary

    runtime.session.coordinator.register_capability(GRAPH_TRANSITION_CAPABILITY, factory)

    def entry(self, level, msg, args, **kwargs):
        entries.append((msg, args, kwargs))

    monkeypatch.setattr(logging.Logger, "_log", entry)
    assert not (await change(runtime, operation)).success
    assert secret not in repr(entries)
    assert all(not item[-1].get("exc_info") and not item[-1].get("stack_info") for item in entries)


@pytest.mark.asyncio
async def test_native_no_capability_preserves_existing_error_logging(runtime, monkeypatch):
    coord = runtime.session.coordinator
    coord.register_capability(GRAPH_TRANSITION_CAPABILITY, None)
    entries = []

    async def broken(*args, **kwargs):
        raise RuntimeError("controlled native-only diagnostic")

    # No participating graph qualification is requested in this compatibility
    # probe. Existing native exception logging is intentionally not broadened.
    monkeypatch.setattr(runtime.tool, "_activate_mode", broken)
    monkeypatch.setattr(
        "amplifier_module_tool_mode.logger.error",
        lambda *args, **kwargs: entries.append((args, kwargs)),
    )
    assert not (await change(runtime)).success
    assert entries == [(("_handle_set failed unexpectedly",), {"exc_info": True})]