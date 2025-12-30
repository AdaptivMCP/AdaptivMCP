from __future__ import annotations

import importlib

from github_mcp.mcp_server import decorators


def _install_fake_mcp(monkeypatch):
    class FakeTool:
        def __init__(self, name, description, tags):
            self.name = name
            self.description = description
            self.tags = tags

    class FakeMCP:
        def tool(self, fn=None, *, name=None, description=None, tags=None, meta=None, annotations=None):
            tool_obj = FakeTool(name, description, tags)
            if fn is None:
                def decorator(inner):
                    tool_obj.fn = inner
                    return tool_obj
                return decorator
            tool_obj.fn = fn
            return tool_obj

    monkeypatch.setattr(decorators, "mcp", FakeMCP())
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])


def test_workspace_tools_schema_excludes_push(monkeypatch):
    _install_fake_mcp(monkeypatch)

    commit_mod = importlib.import_module("github_mcp.workspace_tools.commit")
    git_ops_mod = importlib.import_module("github_mcp.workspace_tools.git_ops")
    commands_mod = importlib.import_module("github_mcp.workspace_tools.commands")

    commit_mod = importlib.reload(commit_mod)
    git_ops_mod = importlib.reload(git_ops_mod)
    commands_mod = importlib.reload(commands_mod)

    commit_schema = commit_mod.commit_workspace.__mcp_input_schema__
    commit_files_schema = commit_mod.commit_workspace_files.__mcp_input_schema__
    create_branch_schema = git_ops_mod.workspace_create_branch.__mcp_input_schema__
    render_shell_schema = commands_mod.render_shell.__mcp_input_schema__

    assert "push" not in commit_schema.get("properties", {})
    assert "push" not in commit_files_schema.get("properties", {})
    assert "push" not in create_branch_schema.get("properties", {})
    assert "push_new_branch" not in render_shell_schema.get("properties", {})
