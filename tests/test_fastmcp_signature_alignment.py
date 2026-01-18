from __future__ import annotations

import inspect

from github_mcp.mcp_server import decorators


def test_fastmcp_signature_alignment_positional_name_fn_factory_fallback(monkeypatch):
    """Ensure we handle FastMCP variants with positional (name, fn, ...) signatures.

    Some FastMCP versions expose `tool(name, fn, *, ...)` (positional name + fn).
    If we attempt keyword-style registration, Python can raise:
      TypeError: ... got multiple values for argument 'name'

    We must fall back to `tool(name, fn, **kw_without_name)`.
    """

    calls = {"positional": 0, "kw_factory": 0}

    class FakeMCP:
        # Signature that forces positional (name, fn, ...)
        def tool(self, name, fn, *, description=None, meta=None, annotations=None):
            calls["positional"] += 1
            assert name == "aligned_tool"
            assert fn is aligned_tool
            assert description == "desc"
            assert isinstance(annotations, dict)
            return {"name": name, "fn": fn, "description": description}

    fake_mcp = FakeMCP()

    # Make our first attempt go through the kw-only factory path and fail with
    # "multiple values" to exercise the fallback.
    original = fake_mcp.tool

    def tool_wrapper(*args, **kwargs):
        # If called kw-only (factory attempt), raise collision-like error.
        if args == () and "name" in kwargs:
            calls["kw_factory"] += 1
            raise TypeError("tool() got multiple values for argument 'name'")
        return original(*args, **kwargs)

    monkeypatch.setattr(fake_mcp, "tool", tool_wrapper)
    monkeypatch.setattr(decorators, "mcp", fake_mcp)
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    # Our wrapper erases the original signature (it becomes *args/**kwargs), which would
    # prevent `_fastmcp_tool_params()` from detecting the positional `(name, fn, ...)` shape.
    # Patch params directly to simulate the real FastMCP signature and ensure the factory
    # fallback path is exercised.
    monkeypatch.setattr(
        decorators,
        "_fastmcp_tool_params",
        lambda: (
            inspect.Parameter(
                "name",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
            inspect.Parameter(
                "fn",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
            inspect.Parameter(
                "description",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
            ),
            inspect.Parameter(
                "meta",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
            ),
            inspect.Parameter(
                "annotations",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
            ),
        ),
    )

    def aligned_tool():
        return "ok"

    tool_obj = decorators._register_with_fastmcp(
        aligned_tool,
        name="aligned_tool",
        description="desc",
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )

    # We should have attempted kw factory once, then succeeded via positional fallback.
    assert calls["kw_factory"] == 1
    assert calls["positional"] == 1
    assert tool_obj["name"] == "aligned_tool"
    assert tool_obj["fn"] is aligned_tool


def test_fastmcp_signature_alignment_does_not_double_register_when_callable_tool_returned(monkeypatch):
    """If FastMCP returns a callable Tool object, we should NOT call it as a decorator.

    This prevents double-registration ("overlapping" tool definitions) which can happen
    if a callable tool instance is invoked.
    """

    class CallableTool:
        def __init__(self, name: str):
            self.name = name

        def __call__(self, *args, **kwargs):
            raise AssertionError("Tool instance should not be invoked")

    class FakeMCP:
        # kw-only factory shape
        def tool(self, *, name=None, description=None, meta=None, annotations=None):
            return CallableTool(name or "tool")

    fake_mcp = FakeMCP()
    monkeypatch.setattr(decorators, "mcp", fake_mcp)
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    def callable_return_tool():
        return "ok"

    tool_obj = decorators._register_with_fastmcp(
        callable_return_tool,
        name="callable_return_tool",
        description="desc",
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
    )

    assert getattr(tool_obj, "name", None) == "callable_return_tool"

    # Ensure registry only contains a single entry for the tool name.
    names = [
        decorators._registered_tool_name(t, f)
        for (t, f) in decorators._REGISTERED_MCP_TOOLS
        if decorators._registered_tool_name(t, f) is not None
    ]
    assert names.count("callable_return_tool") == 1


def test_fastmcp_tool_signature_detection_matches_actual(monkeypatch):
    """Sanity: our parameter inspection should align with the current mcp.tool signature."""

    class FakeMCP:
        def tool(self, fn, *, name=None, description=None, meta=None, annotations=None):
            return {"fn": fn, "name": name}

    fake_mcp = FakeMCP()
    monkeypatch.setattr(decorators, "mcp", fake_mcp)

    params = decorators._fastmcp_tool_params()
    assert params is not None
    assert params[0].name == "fn"
    assert any(p.name == "name" for p in params)

    style = decorators._fastmcp_call_style(params)
    assert style == "direct"

    sig = inspect.signature(fake_mcp.tool)
    assert "fn" in sig.parameters
    assert "name" in sig.parameters
