from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from github_mcp.mcp_server import context as real_context


def _load_context_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_fastmcp_raises_on_tool_registration(monkeypatch: pytest.MonkeyPatch):
    """Runnable even when FastMCP is installed.

    We simulate a missing dependency by injecting a fake `mcp.server.fastmcp`
    module that lacks the `FastMCP` attribute, causing the import in
    github_mcp.mcp_server.context to fail.
    """

    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)

    context_path = Path(real_context.__file__).resolve()
    module_name = "github_mcp.mcp_server._context_missing_fastmcp_test"
    test_context = _load_context_from_path(module_name, context_path)

    try:
        assert test_context.FASTMCP_AVAILABLE is False

        def _tool() -> str:
            return "ok"

        with pytest.raises(RuntimeError, match="FastMCP import failed"):
            test_context.mcp.tool(
                _tool,
                name="missing_fastmcp_tool",
                description="missing fastmcp tool registration",
                tags=set(),
                meta={},
                annotations={},
            )
    finally:
        sys.modules.pop(module_name, None)
