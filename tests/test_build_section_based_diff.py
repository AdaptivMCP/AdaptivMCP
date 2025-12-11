import pytest

import extra_tools
import main


def _register_tools():
    registered = {}

    def fake_mcp_tool(*, write_action=False, **tool_kwargs):
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn

        return decorator

    extra_tools.register_extra_tools(fake_mcp_tool)
    return registered


@pytest.mark.asyncio
async def test_build_section_based_diff_whitespace_only_and_zero_context(monkeypatch):
    tools = _register_tools()
    tool = tools["build_section_based_diff"]

    def fake_effective_ref(full_name, ref):
        return f"scoped/{ref}"

    async def fake_decode(full_name, path, ref):
        assert full_name == "owner/repo"
        assert path == "file.txt"
        assert ref == "scoped/main"
        text = "alpha\nbeta\n"
        return {"text": text, "sha": "oldsha", "numbered_lines": main._with_numbered_lines(text)}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await tool(
        full_name="owner/repo",
        path="file.txt",
        sections=[{"start_line": 2, "end_line": 2, "new_text": "beta \n"}],
        ref="main",
        context_lines=0,
        show_whitespace=True,
    )

    assert result["path"] == "file.txt"
    assert result["full_name"] == "owner/repo"
    assert result["ref"] == "scoped/main"
    assert result["context_lines"] == 0

    patch = result["patch"]
    assert patch.startswith("--- a/file.txt")

    lines = patch.splitlines()
    assert any(line.startswith("-beta") for line in lines)
    assert any(line.startswith("+beta " ) for line in lines)

    for line in lines:
        if not line or line.startswith(("---", "+++", "@@")):
            continue
        assert not line.startswith(" ")

    preview = result.get("preview", "")
    assert preview


@pytest.mark.asyncio
async def test_build_section_based_diff_empty_file_insertion(monkeypatch):
    tools = _register_tools()
    tool = tools["build_section_based_diff"]

    def fake_effective_ref(full_name, ref):
        return ref

    async def fake_decode(full_name, path, ref):
        text = ""
        return {"text": text, "sha": "oldsha", "numbered_lines": main._with_numbered_lines(text)}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await tool(
        full_name="owner/repo",
        path="empty.txt",
        sections=[{"start_line": 1, "end_line": 0, "new_text": "hello\nworld\n"}],
        ref="main",
        context_lines=3,
        show_whitespace=False,
    )

    patch = result["patch"]
    assert patch
    assert patch.startswith("--- a/empty.txt")
    assert "+hello" in patch
    assert "+world" in patch

    applied = result["applied_sections"]
    assert len(applied) == 1
    assert applied[0]["start_line"] == 1
    assert applied[0]["end_line"] == 0


@pytest.mark.asyncio
async def test_build_section_based_diff_rejects_negative_context():
    tools = _register_tools()
    tool = tools["build_section_based_diff"]

    with pytest.raises(ValueError, match="context_lines must be >= 0"):
        await tool(
            full_name="owner/repo",
            path="file.txt",
            sections=[{"start_line": 1, "end_line": 1, "new_text": "x\n"}],
            ref="main",
            context_lines=-1,
        )
