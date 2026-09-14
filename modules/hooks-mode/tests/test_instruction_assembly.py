"""Optional integration seam against the exact context-simple v1 source.

Set ``AMPLIFIER_CONTEXT_SIMPLE_TEST_SOURCE`` to the checkout containing
``amplifier_module_context_simple``.  Production hooks-mode never imports this
module; the test loads it only when an integration checkout is supplied.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_module_hooks_mode import ModeDiscovery, ModeHooks

_SOURCE_ENV = "AMPLIFIER_CONTEXT_SIMPLE_TEST_SOURCE"


def _write_mode(directory: Path, name: str, body: str) -> None:
    (directory / f"{name}.md").write_text(
        f"""---
mode:
  name: {name}
  default_action: allow
---
{body}
""",
        encoding="utf-8",
    )


@pytest.fixture
def context_simple_api(monkeypatch: pytest.MonkeyPatch):
    source = os.environ.get(_SOURCE_ENV)
    if not source:
        pytest.skip(f"set {_SOURCE_ENV} to run the real v1 integration seam")

    root = Path(source).resolve()
    if not (root / "amplifier_module_context_simple" / "__init__.py").is_file():
        pytest.fail(f"{_SOURCE_ENV} is not a context-simple source checkout: {root}")

    monkeypatch.syspath_prepend(str(root))
    importlib.invalidate_caches()
    package = importlib.import_module("amplifier_module_context_simple")
    instructions = importlib.import_module("amplifier_module_context_simple.instructions")
    assert Path(package.__file__).resolve().is_relative_to(root)
    return package.SimpleContextManager, instructions.InstructionAssembly


class _Coordinator:
    def __init__(self) -> None:
        self.capabilities: dict[str, object] = {}
        self.session_state: dict[str, object] = {
            "active_mode": None,
            "require_approval_tools": set(),
        }
        self.hooks = MagicMock()
        self.hooks.emit = AsyncMock()

    def register_capability(self, name: str, value: object) -> None:
        self.capabilities[name] = value

    def get_capability(self, name: str):
        return self.capabilities.get(name)

    async def process_hook_result(self, result, **_kwargs):
        return result


class _Provider:
    instruction_layout_version = 1


async def _add_human_input(context, assembly, input_id: str) -> dict[str, str]:
    with assembly.input_scope("human", input_id):
        await context.add_message({"role": "user", "content": input_id})
    return context.messages[-1]["metadata"]["amplifier:input"]


async def _request(context, assembly, hooks, request_id: str, anchor: dict[str, str]):
    async with assembly.turn(f"turn-{request_id}", anchor):
        async with assembly.request(
            {
                "turn_id": f"turn-{request_id}",
                "request_id": request_id,
                "llm_step_id": f"step-{request_id}",
                "input_anchor": anchor,
                "completed_batches": [],
                "tail_anchor": None,
            },
            _Provider(),
        ):
            result = await hooks.handle_provider_request("provider:request", {})
            return result, await context.get_messages_for_request()


@pytest.mark.asyncio
async def test_v1_mode_source_admits_one_fresh_current_record_each_request(
    context_simple_api, tmp_path: Path
) -> None:
    """The real assembler admits mode A, mode B, then no stale mode after off."""
    simple_context, instruction_assembly = context_simple_api
    modes_dir = tmp_path / "modes"
    modes_dir.mkdir()
    _write_mode(modes_dir, "mode-a", "MODE-A-BODY")
    _write_mode(modes_dir, "mode-b", "MODE-B-BODY")
    contributed = tmp_path / "contributed.md"
    contributed.write_text("CONTRIBUTED-MODE-A-CONTEXT", encoding="utf-8")

    coordinator = _Coordinator()
    resolver = MagicMock()
    resolver.resolve.return_value = str(contributed)
    coordinator.register_capability(
        "runtime_context_overlay", ["@test:context/contributed.md"]
    )
    coordinator.register_capability("mention_resolver", resolver)
    context = simple_context(
        max_tokens=2_000,
        compact_threshold=0.9,
        target_usage=0.5,
        compaction_notice_enabled=False,
    )
    assembly = instruction_assembly(context, coordinator, session_id="modes-test")
    context._instruction_assembly = assembly
    coordinator.register_capability("context.instructions.v1", assembly)
    hooks = ModeHooks(coordinator, ModeDiscovery(search_paths=[modes_dir]))
    hooks.register_instruction_source(assembly)

    coordinator.session_state["active_mode"] = "mode-a"
    first, first_view = await _request(
        context, assembly, hooks, "request-a", await _add_human_input(context, assembly, "a")
    )
    assert first.action == "continue"
    first_contents = [item["content"] for item in first_view]
    assert sum("MODE-A-BODY" in content for content in first_contents) == 1
    assert sum("CONTRIBUTED-MODE-A-CONTEXT" in content for content in first_contents) == 1

    coordinator.session_state["active_mode"] = "mode-b"
    coordinator.register_capability("runtime_context_overlay", [])
    second, second_view = await _request(
        context, assembly, hooks, "request-b", await _add_human_input(context, assembly, "b")
    )
    second_contents = [item["content"] for item in second_view]
    assert second.action == "continue"
    assert sum("MODE-B-BODY" in content for content in second_contents) == 1
    assert not any("MODE-A-BODY" in content for content in second_contents)
    assert not any("CONTRIBUTED-MODE-A-CONTEXT" in content for content in second_contents)

    coordinator.session_state["active_mode"] = None
    third, third_view = await _request(
        context, assembly, hooks, "request-off", await _add_human_input(context, assembly, "off")
    )
    third_contents = [item["content"] for item in third_view]
    assert third.action == "continue"
    assert any("No mode is currently active." in content for content in third_contents)
    assert not any("MODE-B-BODY" in content for content in third_contents)
