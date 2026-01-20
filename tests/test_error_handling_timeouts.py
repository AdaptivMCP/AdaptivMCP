import asyncio

from github_mcp.mcp_server.error_handling import _structured_tool_error


def test_structured_tool_error_timeout_marks_retryable() -> None:
    error = _structured_tool_error(TimeoutError("request timed out"), context="test")

    detail = error["error_detail"]
    assert detail["category"] == "timeout"
    assert detail["retryable"] is True
    assert detail["message"] == "request timed out"


def test_structured_tool_error_asyncio_timeout_marks_retryable() -> None:
    error = _structured_tool_error(asyncio.TimeoutError(), context="test")

    detail = error["error_detail"]
    assert detail["category"] == "timeout"
    assert detail["retryable"] is True
