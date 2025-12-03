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
async def test_apply_line_edits_and_commit_minimal_payload(monkeypatch):
    tools = _register_tools()
    tool = tools["apply_line_edits_and_commit"]

    calls = {}

    def fake_effective_ref(full_name, branch):
        calls["effective_ref"] = (full_name, branch)
        return f"scoped/{branch}"

    async def fake_decode(full_name, path, ref):
        calls["decode"] = (full_name, path, ref)
        return {"text": "line1\nline2\nline3\n", "sha": "oldsha"}

    async def fake_apply_text_update_and_commit(
        full_name,
        path,
        updated_content,
        *,
        branch,
        message,
        return_diff,
        context_lines,
    ):
        calls["apply"] = {
            "full_name": full_name,
            "path": path,
            "branch": branch,
            "message": message,
            "return_diff": return_diff,
            "context_lines": context_lines,
            "updated_content": updated_content,
        }
        return {
            "status": "committed",
            "full_name": full_name,
            "path": path,
            "branch": branch,
            "message": message,
            "commit": {"sha": "newsha"},
            "verification": {"sha_before": "old", "sha_after": "new"},
        }

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)
    monkeypatch.setattr(
        main, "apply_text_update_and_commit", fake_apply_text_update_and_commit
    )

    result = await tool(
        full_name="owner/repo",
        path="README.md",
        sections=[{"start_line": 2, "end_line": 2, "new_text": "replacement line\n"}],
        branch="feature",
        message="Tight edit",
        include_diff=False,
        context_lines=2,
    )

    assert calls["effective_ref"] == ("owner/repo", "feature")
    assert calls["decode"] == ("owner/repo", "README.md", "scoped/feature")

    apply_call = calls["apply"]
    assert apply_call["branch"] == "scoped/feature"
    assert apply_call["message"] == "Tight edit"
    assert apply_call["return_diff"] is False
    assert apply_call["context_lines"] == 2
    assert apply_call["updated_content"] == "line1\nreplacement line\nline3\n"

    assert result["status"] == "committed"
    assert result["applied_sections"][0]["start_line"] == 2
    assert result["context_lines"] == 2


@pytest.mark.asyncio
async def test_apply_line_edits_and_commit_appends(monkeypatch):
    tools = _register_tools()
    tool = tools["apply_line_edits_and_commit"]

    def fake_effective_ref(full_name, branch):
        return f"scoped/{branch}"

    async def fake_decode(full_name, path, ref):
        return {"text": "a\nb\nc\n", "sha": "oldsha"}

    calls = {}

    async def fake_apply_text_update_and_commit(**kwargs):
        calls.update(kwargs)
        return {"status": "committed", "commit": {"sha": "newsha"}}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "apply_text_update_and_commit", fake_apply_text_update_and_commit)

    result = await tool(
        full_name="owner/repo",
        path="README.md",
        sections=[{"start_line": 4, "end_line": 4, "new_text": "d\n"}],
        branch="feature",
    )

    assert calls["updated_content"] == "a\nb\nc\nd\n"
    assert result["status"] == "committed"


@pytest.mark.asyncio
async def test_apply_line_edits_and_commit_noop(monkeypatch):
    tools = _register_tools()
    tool = tools["apply_line_edits_and_commit"]

    def fake_effective_ref(full_name, branch):
        return f"scoped/{branch}"

    async def fake_decode(full_name, path, ref):
        return {"text": "same\n", "sha": "sha"}

    apply_called = False

    async def fake_apply(*args, **kwargs):
        nonlocal apply_called
        apply_called = True
        return {}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "apply_text_update_and_commit", fake_apply)

    result = await tool(
        full_name="owner/repo",
        path="file.txt",
        sections=[{"start_line": 1, "end_line": 1, "new_text": "same\n"}],
    )

    assert result["status"] == "no-op"
    assert result["reason"] == "no_changes"
    assert result["branch"] == "scoped/main"
    assert apply_called is False
