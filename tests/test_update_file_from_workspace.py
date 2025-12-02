import base64

import pytest

import extra_tools


def _register_update_file_tool():
    """Register extra tools with a dummy mcp_tool and return update_file_from_workspace.

    This mirrors how extra_tools.register_extra_tools is used in the server, but keeps
    the test focused on the behavior of the tool function itself.
    """
    registered = {}

    def fake_mcp_tool(*, write_action=False, **tool_kwargs):
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn

        return decorator

    extra_tools.register_extra_tools(fake_mcp_tool)
    return registered["update_file_from_workspace"]


@pytest.mark.asyncio
async def test_update_file_from_workspace_creates_new_file(monkeypatch, tmp_path):
    tool = _register_update_file_tool()

    calls = {}

    async def fake_resolve_file_sha(full_name, path, branch):
        calls["resolve"] = (full_name, path, branch)
        return None

    async def fake_github_request(method, path, json_body=None, expect_json=True):
        calls["request"] = {
            "method": method,
            "path": path,
            "json_body": json_body,
            "expect_json": expect_json,
        }
        return {"ok": True}

    def fake_workspace_path(full_name, ref):
        return str(tmp_path)

    def fake_effective_ref(full_name, branch):
        return f"ref/{branch}"

    monkeypatch.setattr(extra_tools, "_resolve_file_sha", fake_resolve_file_sha)
    monkeypatch.setattr(extra_tools, "_github_request", fake_github_request)
    monkeypatch.setattr(extra_tools, "_workspace_path", fake_workspace_path)
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)

    workspace_file = tmp_path / "dir" / "file.txt"
    workspace_file.parent.mkdir(parents=True, exist_ok=True)
    workspace_file.write_text("hello from workspace", encoding="utf-8")

    result = await tool(
        full_name="owner/repo",
        branch="feature",
        workspace_path="dir/file.txt",
        target_path="repo/file.txt",
        message="Commit from workspace",
    )

    assert result["full_name"] == "owner/repo"
    assert result["branch"] == "ref/feature"
    assert result["workspace_path"] == "dir/file.txt"
    assert result["target_path"] == "repo/file.txt"

    assert calls["resolve"] == ("owner/repo", "repo/file.txt", "ref/feature")

    req = calls["request"]
    assert req["method"] == "PUT"
    assert req["path"] == "/repos/owner/repo/contents/repo/file.txt"
    body = req["json_body"]
    assert body["message"] == "Commit from workspace"
    assert body["branch"] == "ref/feature"
    assert "sha" not in body

    encoded = body["content"]
    decoded = base64.b64decode(encoded.encode("ascii"))
    assert decoded == b"hello from workspace"
    assert req["expect_json"] is True


@pytest.mark.asyncio
async def test_update_file_from_workspace_missing_workspace_file(monkeypatch, tmp_path):
    tool = _register_update_file_tool()

    def fake_workspace_path(full_name, ref):
        return str(tmp_path)

    def fake_effective_ref(full_name, branch):
        return f"ref/{branch}"

    monkeypatch.setattr(extra_tools, "_workspace_path", fake_workspace_path)
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)

    with pytest.raises(FileNotFoundError):
        await tool(
            full_name="owner/repo",
            branch="feature",
            workspace_path="missing.txt",
            target_path="missing.txt",
            message="Commit from workspace",
        )
