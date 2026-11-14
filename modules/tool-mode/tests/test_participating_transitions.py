"""Actual ModeTool + hooks-mode on Core, using public issuer operations only.

Synthetic component integration, not an installed-host/provider qualification.
Foundation is supplied by the test host, not a new modes runtime dependency.
"""

import asyncio
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