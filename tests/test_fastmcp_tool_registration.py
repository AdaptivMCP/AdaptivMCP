from __future__ import annotations

import pytest

from github_mcp.mcp_server import decorators


def test_register_with_fastmcp_skips_unsupported_kwargs(monkeypatch):
    class FakeMCP:
        def tool(self, *, name=None, description=None, meta=None, annotations=None):
            assert name == "sample_tool"
            assert description == "sample description"
            assert meta == {}
            assert isinstance(annotations, dict)
            assert set(annotations.keys()) >= {"readOnlyHint", "destructiveHint", "openWorldHint"}

            def decorator(fn):
                return {"fn": fn, "name": name}

            return decorator

    fake_mcp = FakeMCP()
    monkeypatch.setattr(decorators, "mcp", fake_mcp)
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    def sample_tool():
        return "ok"

    tool_obj = decorators._register_with_fastmcp(
        sample_tool,
        name="sample_tool",
        description="sample description",
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )
    assert tool_obj["fn"] is sample_tool
    assert tool_obj["name"] == "sample_tool"


def test_register_with_fastmcp_requires_fn_positional(monkeypatch):
    class FakeMCP:
        def tool(self, fn, *, name=None, description=None, meta=None, annotations=None):
            assert name == "positional_tool"
            assert description == "positional description"
            assert isinstance(annotations, dict)
            assert set(annotations.keys()) >= {"readOnlyHint", "destructiveHint", "openWorldHint"}
            return {"fn": fn, "name": name}

    fake_mcp = FakeMCP()
    monkeypatch.setattr(decorators, "mcp", fake_mcp)
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    def positional_tool():
        return "ok"

    tool_obj = decorators._register_with_fastmcp(
        positional_tool,
        name="positional_tool",
        description="positional description",
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )
    assert tool_obj["fn"] is positional_tool
    assert tool_obj["name"] == "positional_tool"


def test_register_with_fastmcp_does_not_emit_tags(monkeypatch):
    captured = {}

    class FakeMCP:
        def tool(
            self,
            fn=None,
            *,
            name=None,
            description=None,
            tags=None,
            meta=None,
            annotations=None,
        ):
            captured["tags"] = tags

            if fn is None:

                def decorator(inner):
                    return {"fn": inner, "name": name, "tags": tags}

                return decorator
            return {"fn": fn, "name": name, "tags": tags}

    fake_mcp = FakeMCP()
    monkeypatch.setattr(decorators, "mcp", fake_mcp)
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    def tagged_tool():
        return "ok"

    decorators._register_with_fastmcp(
        tagged_tool,
        name="tagged_tool",
        description="tagged description",
        tags=["alpha", "beta"],
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )
    assert captured["tags"] is None


def test_mcp_tool_preserves_scalar_returns_sync(monkeypatch):
    class FakeMCP:
        def tool(self, *, name=None, description=None, meta=None, annotations=None):
            def decorator(fn):
                return {"fn": fn, "name": name}

            return decorator

    monkeypatch.setattr(decorators, "mcp", FakeMCP())
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    @decorators.mcp_tool(name="sync_tool", write_action=False)
    def sync_tool() -> str:
        return "ok"

    assert sync_tool() == "ok"

    # Ensure annotations are attached for UI metadata.
    tool_obj = sync_tool.__mcp_tool__
    ann = getattr(tool_obj, "annotations", None)
    if not isinstance(ann, dict) and isinstance(tool_obj, dict):
        ann = tool_obj.get("annotations")
    assert isinstance(ann, dict)
    assert set(ann.keys()) >= {"readOnlyHint", "destructiveHint", "openWorldHint"}


@pytest.mark.anyio
async def test_mcp_tool_preserves_scalar_returns_async(monkeypatch):
    class FakeMCP:
        def tool(self, *, name=None, description=None, meta=None, annotations=None):
            def decorator(fn):
                return {"fn": fn, "name": name}

            return decorator

    monkeypatch.setattr(decorators, "mcp", FakeMCP())
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    @decorators.mcp_tool(name="async_tool", write_action=False)
    async def async_tool() -> str:
        return "ok"

    assert await async_tool() == "ok"

    tool_obj = async_tool.__mcp_tool__
    ann = getattr(tool_obj, "annotations", None)
    if not isinstance(ann, dict) and isinstance(tool_obj, dict):
        ann = tool_obj.get("annotations")
    assert isinstance(ann, dict)
    assert set(ann.keys()) >= {"readOnlyHint", "destructiveHint", "openWorldHint"}


def test_mcp_tool_does_not_inject_ui_fields_for_mapping_returns(monkeypatch):
    class FakeMCP:
        def tool(self, *, name=None, description=None, meta=None, annotations=None):
            def decorator(fn):
                return {"fn": fn, "name": name}

            return decorator

    monkeypatch.setattr(decorators, "mcp", FakeMCP())
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    @decorators.mcp_tool(name="mapping_tool", write_action=False)
    def mapping_tool() -> dict:
        return {"foo": "bar"}

    out = mapping_tool()
    assert out == {"foo": "bar"}
