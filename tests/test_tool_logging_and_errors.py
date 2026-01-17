import logging

import pytest


def test_tool_result_outcome_detects_terminal_failures() -> None:
    # Private helper import is intentional: this is the canonical classifier used
    # by the tool wrapper for success/warning/error routing.
    from github_mcp.mcp_server.decorators import _tool_result_outcome

    assert _tool_result_outcome({"exit_code": 1, "timed_out": False}) == "error"
    assert _tool_result_outcome({"exit_code": 0, "timed_out": True}) == "error"
    assert _tool_result_outcome({"result": {"exit_code": 2}}) == "error"
    assert _tool_result_outcome({"result": {"timed_out": True}}) == "error"
    assert _tool_result_outcome({"exit_code": 0, "timed_out": False}) == "ok"


def test_tool_result_outcome_handles_cancelled_as_warning() -> None:
    from github_mcp.mcp_server.decorators import _tool_result_outcome

    assert _tool_result_outcome({"status": "cancelled"}) == "warning"
    assert _tool_result_outcome({"status": "canceled"}) == "warning"


def test_emit_tool_error_includes_trace_and_args() -> None:
    from github_mcp.mcp_server.decorators import _emit_tool_error

    err = _emit_tool_error(
        tool_name="unit_test_tool",
        call_id="00000000-0000-0000-0000-000000000000",
        write_action=False,
        start=0.0,
        schema_hash=None,
        schema_present=False,
        req={"path": "/test"},
        exc=ValueError("bad input"),
        phase="execute",
        all_args={"path": "README.md", "n": 1},
    )
    assert err.get("status") == "error"
    detail = err.get("error_detail")
    assert isinstance(detail, dict)
    assert detail.get("trace", {}).get("phase") == "execute"
    debug = detail.get("debug")
    assert isinstance(debug, dict)
    assert isinstance(debug.get("args"), dict)
    assert debug["args"].get("path")


def test_failure_logs_emit_at_error_level(caplog: pytest.LogCaptureFixture) -> None:
    from github_mcp.mcp_server.decorators import _log_tool_failure

    caplog.set_level(logging.INFO)
    _log_tool_failure(
        tool_name="unit_test_tool",
        call_id="00000000-0000-0000-0000-000000000000",
        write_action=False,
        req={"path": "/test"},
        schema_hash=None,
        schema_present=False,
        duration_ms=12.3,
        phase="execute",
        exc=RuntimeError("boom"),
        all_args={"x": 1},
        structured_error={"error": "boom"},
    )
    assert any(rec.levelno == logging.ERROR for rec in caplog.records)


def test_returned_error_logs_emit_at_error_level(caplog: pytest.LogCaptureFixture) -> None:
    from github_mcp.mcp_server.decorators import _log_tool_returned_error

    caplog.set_level(logging.INFO)
    _log_tool_returned_error(
        tool_name="unit_test_tool",
        call_id="00000000-0000-0000-0000-000000000000",
        write_action=False,
        req={"path": "/test"},
        schema_hash=None,
        schema_present=False,
        duration_ms=5.0,
        result={"error": "nope", "status": "error", "ok": False},
        all_args={"x": 1},
    )
    assert any(rec.levelno == logging.ERROR for rec in caplog.records)
