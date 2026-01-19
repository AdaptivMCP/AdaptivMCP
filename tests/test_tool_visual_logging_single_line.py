import importlib
import os


def _reload_decorators_with_env(**env: str):
    for k, v in env.items():
        os.environ[k] = v
    import github_mcp.mcp_server.decorators as decorators  # type: ignore

    return importlib.reload(decorators)


class _FakeLogger:
    def __init__(self, sink):
        self._sink = sink

    def info(self, msg: str, *, extra=None, **kwargs):  # noqa: ANN001
        self._sink.append((msg, extra or {}, kwargs))


def test_log_tool_visual_emits_single_line_message(monkeypatch) -> None:
    decorators = _reload_decorators_with_env(
        GITHUB_MCP_LOG_TOOL_CALLS="1",
        GITHUB_MCP_HUMAN_LOGS="1",
        GITHUB_MCP_LOG_VISUALS="1",
        GITHUB_MCP_LOG_COLOR="0",
    )

    calls = []
    monkeypatch.setattr(decorators, "LOGGER", _FakeLogger(calls))

    decorators._log_tool_visual(
        tool_name="terminal_command",
        call_id="abc123",
        req={"headers": {}, "client": {"host": "127.0.0.1"}},
        kind="terminal",
        visual="stdout\n   1│ hello\n   2│ world\n",
    )

    assert calls, "expected a log call"
    msg, extra, _ = calls[-1]

    # Provider logs are line-oriented; keep message single line.
    assert "\n" not in msg

    # Full visual is preserved in structured fields.
    assert extra.get("event") == "tool_visual"
    assert "stdout" in str(extra.get("visual") or "")
    assert isinstance(extra.get("visual_preview"), str)
    assert int(extra.get("visual_lines") or 0) >= 1


def test_suites_normalizes_carriage_returns() -> None:
    from github_mcp.workspace_tools import suites

    payload = {
        "result": {
            "stdout": "a\r\nb\rc\n",
            "stderr": "x\ry\n",
            "exit_code": 0,
            "timed_out": False,
        }
    }
    shaped = suites._slim_terminal_command_payload(payload)

    stdout = shaped.get("stdout") or ""
    stderr = shaped.get("stderr") or ""

    assert "\r" not in stdout
    assert "\r" not in stderr
    assert stdout.count("\n") >= 2
    assert stderr.count("\n") >= 1
