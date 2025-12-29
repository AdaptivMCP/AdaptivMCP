from __future__ import annotations

from github_mcp.mcp_server import decorators


def test_register_with_fastmcp_skips_unsupported_kwargs(monkeypatch):
    class FakeMCP:
        def tool(self, *, name=None, description=None, meta=None, annotations=None):
            assert name == "sample_tool"
            assert description == "sample description"
            assert meta == {}
            assert annotations == {}

            def decorator(fn):
                return {"fn": fn, "name": name}

            return decorator

    fake_mcp = FakeMCP()
    monkeypatch.setattr(decorators, "mcp", fake_mcp)
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    def sample_tool():
        return "ok"

    tool_obj = decorators._register_with_fastmcp(sample_tool, name="sample_tool", description="sample description")
    assert tool_obj["fn"] is sample_tool
    assert tool_obj["name"] == "sample_tool"


def test_register_with_fastmcp_requires_fn_positional(monkeypatch):
    class FakeMCP:
        def tool(self, fn, *, name=None, description=None, meta=None, annotations=None):
            assert name == "positional_tool"
            assert description == "positional description"
            return {"fn": fn, "name": name}

    fake_mcp = FakeMCP()
    monkeypatch.setattr(decorators, "mcp", fake_mcp)
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    def positional_tool():
        return "ok"

    tool_obj = decorators._register_with_fastmcp(
        positional_tool, name="positional_tool", description="positional description"
    )
    assert tool_obj["fn"] is positional_tool
    assert tool_obj["name"] == "positional_tool"
