import logging
import uuid

import pytest

import main


@pytest.mark.asyncio
async def test_async_tool_logging_success(caplog):
    caplog.set_level(logging.INFO, logger="github_mcp.tools")

    # Use a simple async tool that does not talk to GitHub so the test is
    # hermetic. get_server_config is defined with @mcp_tool and should be
    # wrapped by the logging decorator.
    with caplog.at_level(logging.INFO, logger="github_mcp.tools"):
        result = await main.get_server_config()

    assert isinstance(result, dict)

    start_records = [r for r in caplog.records if r.message == "tool_call_start"]
    success_records = [r for r in caplog.records if r.message == "tool_call_success"]

    assert start_records, caplog.text
    assert success_records, caplog.text

    start = start_records[-1]
    success = success_records[-1]

    assert start.tool_name == "get_server_config"
    assert success.tool_name == "get_server_config"
    assert start.call_id == success.call_id
    assert isinstance(success.duration_ms, int) and success.duration_ms >= 0
    assert success.status == "ok"


@pytest.mark.asyncio
async def test_async_tool_logging_error(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="github_mcp.tools")

    # Define a simple failing tool via the same decorator so that it is wrapped
    # by the logging layer but does not depend on network access.
    @main.mcp_tool(write_action=False)
    async def failing_tool() -> None:  # pragma: no cover - body always fails
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="github_mcp.tools"):
        with pytest.raises(RuntimeError):
            await failing_tool()

    error_records = [r for r in caplog.records if r.message == "tool_call_error"]
    assert error_records, caplog.text
    err = error_records[-1]
    assert err.tool_name == "failing_tool"
    assert err.status == "error"
    assert err.error_type == "RuntimeError"
    assert isinstance(err.duration_ms, int) and err.duration_ms >= 0
