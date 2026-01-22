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


def test_log_tool_summary_emits_single_line_message(monkeypatch) -> None:
    decorators = _reload_decorators_with_env(
        ADAPTIV_MCP_LOG_TOOL_CALLS="1",
        ADAPTIV_MCP_HUMAN_LOGS="1",
        ADAPTIV_MCP_LOG_COLOR="0",
    )

    calls = []
    monkeypatch.setattr(decorators, "LOGGER", _FakeLogger(calls))

    decorators._log_tool_summary(
        tool_name="create_workspace_folders",
        call_id="abc123",
        write_action=True,
        req={"headers": {}, "client": {"host": "127.0.0.1"}},
        schema_hash=None,
        schema_present=False,
        result={"status": "created", "created": ["docs", "tests"], "failed": []},
        all_args={"paths": ["docs", "tests"]},
    )

    assert calls, "expected a log call"
    msg, extra, _ = calls[-1]

    # Provider logs are line-oriented; keep message single line.
    assert "\n" not in msg

    assert extra.get("event") == "tool_call_report"
    report = extra.get("report") or {}
    assert "Created 2 items" in str(report.get("summary") or "")


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
