"""Tests for the mode-author agent file.

Verifies that agents/mode-author.md exists, has valid YAML frontmatter,
and contains all required structural elements per the spec.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Locate bundle root — three parents up from this file's package dir.
# modules/hooks-mode/tests/test_mode_author_agent.py → bundle root is parents[3].
BUNDLE_ROOT = Path(__file__).resolve().parents[3]
AGENT_FILE = BUNDLE_ROOT / "agents" / "mode-author.md"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from a markdown file."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    return fm, body


def test_agent_file_exists() -> None:
    """agents/mode-author.md must exist at the expected path."""
    assert AGENT_FILE.is_file(), (
        f"Agent file not found at {AGENT_FILE}. "
        "Create amplifier-bundle-modes/agents/mode-author.md."
    )


def test_frontmatter_parses() -> None:
    """YAML frontmatter must be valid and parseable."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    fm, _ = _parse_frontmatter(content)
    assert fm, "YAML frontmatter is empty or missing"
    assert "meta" in fm, "frontmatter must have a 'meta' key"


def test_meta_name_is_mode_author() -> None:
    """meta.name must be 'mode-author'."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    fm, _ = _parse_frontmatter(content)
    assert fm.get("meta", {}).get("name") == "mode-author", (
        f"meta.name must be 'mode-author', got {fm.get('meta', {}).get('name')!r}"
    )


def test_meta_description_has_two_examples() -> None:
    """meta.description must contain at least two <example> blocks."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    fm, _ = _parse_frontmatter(content)
    description = fm.get("meta", {}).get("description", "")
    example_count = description.count("<example>")
    assert example_count >= 2, (
        f"meta.description must contain at least 2 <example> blocks, found {example_count}"
    )


def test_model_role_includes_reasoning_and_general() -> None:
    """model_role must include both 'reasoning' and 'general'.
    
    model_role may be at top level or inside meta (accepts both patterns).
    """
    content = AGENT_FILE.read_text(encoding="utf-8")
    fm, _ = _parse_frontmatter(content)
    # model_role can be at top level (like most agent files) or inside meta
    model_role = fm.get("model_role") or fm.get("meta", {}).get("model_role")
    assert model_role is not None, "model_role must be set (at top level or inside meta)"
    if isinstance(model_role, list):
        roles = model_role
    else:
        roles = [model_role]
    assert "reasoning" in roles, f"model_role must include 'reasoning', got {roles}"
    assert "general" in roles, f"model_role must include 'general', got {roles}"


def test_tools_has_filesystem_module() -> None:
    """tools section must include tool-filesystem from the expected source."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    fm, _ = _parse_frontmatter(content)
    tools = fm.get("tools", [])
    assert tools, "tools section must be present and non-empty"
    modules = [t.get("module") for t in tools if isinstance(t, dict)]
    assert "tool-filesystem" in modules, (
        f"tools must include 'tool-filesystem', got modules: {modules}"
    )
    filesystem_source = next(
        (t.get("source") for t in tools if isinstance(t, dict) and t.get("module") == "tool-filesystem"),
        None,
    )
    assert "amplifier-module-tool-filesystem" in (filesystem_source or ""), (
        f"tool-filesystem source must reference amplifier-module-tool-filesystem, got: {filesystem_source}"
    )


def test_body_has_your_role_section() -> None:
    """Body must contain a 'Your Role' section."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(content)
    assert "Your Role" in body, (
        "Body must contain a 'Your Role' section"
    )


def test_body_has_output_file_template() -> None:
    """Body must contain an Output File Template section."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(content)
    assert "Output File Template" in body, (
        "Body must contain an 'Output File Template' section"
    )


def test_body_has_discipline_section() -> None:
    """Body must contain a Discipline rules section."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(content)
    assert "Discipline" in body, (
        "Body must contain a 'Discipline' section"
    )


def test_body_has_red_flags_section() -> None:
    """Body must contain a Red Flags section."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(content)
    assert "Red Flag" in body, (
        "Body must contain a 'Red Flags' section"
    )


def test_body_includes_common_agent_base() -> None:
    """Body must include @foundation:context/shared/common-agent-base.md."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(content)
    assert "@foundation:context/shared/common-agent-base.md" in body, (
        "Body must include @foundation:context/shared/common-agent-base.md"
    )


def test_example_blocks_contain_expected_scenarios() -> None:
    """Examples must cover design-conversation and settled-intent scenarios."""
    content = AGENT_FILE.read_text(encoding="utf-8")
    fm, _ = _parse_frontmatter(content)
    description = fm.get("meta", {}).get("description", "")
    # One example for 'Draft the mode file' / design conversation
    assert "draft" in description.lower() or "mode file" in description.lower(), (
        "meta.description must include an example about drafting a mode file"
    )
    # Second example for settled intent / 'Write the mode'
    assert "write" in description.lower() or "settled" in description.lower(), (
        "meta.description must include an example about writing from settled intent"
    )
