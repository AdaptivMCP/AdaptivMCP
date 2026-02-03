import pytest

from github_mcp.mcp_server import decorators as dec


def _prepare_compact_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "LOG_TOOL_CALLS", False)
    monkeypatch.setattr(dec, "FASTMCP_AVAILABLE", False)
    monkeypatch.setattr(dec, "mcp", None)
    monkeypatch.setattr(
        dec, "get_request_context", lambda: {"response_mode": "compact"}
    )
    monkeypatch.setattr(dec, "_REGISTERED_MCP_TOOLS", [])


def test_mcp_tool_compact_mode_shape_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_compact_mode(monkeypatch)

    @dec.mcp_tool(write_action=False)
    def demo(value: int) -> dict[str, int]:
        return {"value": value}

    result = demo(1)

    assert result["tool"] == "demo"
    assert "data" in result


@pytest.mark.anyio
async def test_mcp_tool_compact_mode_shape_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_compact_mode(monkeypatch)

    @dec.mcp_tool(write_action=False)
    async def demo(value: int) -> dict[str, int]:
        return {"value": value}

    result = await demo(1)

    assert result["tool"] == "demo"
    assert "data" in result
