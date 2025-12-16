import main
from github_mcp.config import ERROR_LOG_HANDLER, ERROR_LOG_CAPACITY
from github_mcp.server import _structured_tool_error


class DummyToolError(RuntimeError):
    pass


def test_get_recent_server_errors_captures_structured_errors():
    # Start from a clean buffer.
    try:
        ERROR_LOG_HANDLER._records.clear()  # type: ignore[attr-defined]
    except Exception:
        # Fallback: drop via records snapshot semantics if internals change.
        _ = ERROR_LOG_HANDLER.records

    exc = DummyToolError("boom")
    _structured_tool_error(exc, context="test_recent_errors", path="/tmp/example.py")

    result = main.get_recent_server_errors(limit=10)

    expected_limit = 10 if ERROR_LOG_CAPACITY <= 0 else min(10, ERROR_LOG_CAPACITY)
    assert result["limit"] == expected_limit
    expected_capacity = None if ERROR_LOG_CAPACITY <= 0 else ERROR_LOG_CAPACITY
    assert result["capacity"] == expected_capacity
    errors = result["errors"]
    assert isinstance(errors, list)
    assert errors, "expected at least one error record"

    latest = errors[0]
    assert latest["logger"].startswith("github_mcp")
    assert latest["level"] == "ERROR"
    assert latest["tool_context"] == "test_recent_errors"
    assert latest["tool_error_type"] == "DummyToolError"
    assert latest["tool_error_message"]
    assert latest["tool_error_origin"]
    assert latest["tool_error_category"]
