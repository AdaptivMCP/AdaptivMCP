from __future__ import annotations

import github_mcp.mcp_server.decorators as dec

_chatgpt_friendly_result = dec._chatgpt_friendly_result


def test_chatgpt_friendly_result_surfaces_stdout_and_stderr(monkeypatch):
    # The implementation disables response shaping under pytest for safety.
    # For this unit test we explicitly enable the shaping path.
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "chatgpt")

    payload = {
        "status": "ok",
        "ok": True,
        "result": {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "hello\nworld\n",
            "stderr": "warn: nope\n",
        },
    }

    shaped = _chatgpt_friendly_result(payload, req={"headers": {}})
    assert isinstance(shaped, dict)

    report = shaped.get("report")
    assert isinstance(report, dict)
    streams = report.get("streams")
    assert isinstance(streams, dict)

    # Streams live under report.streams to avoid duplicating payload fields.
    assert streams.get("stdout") == "hello\nworld\n"
    assert streams.get("stderr") == "warn: nope\n"
    assert streams.get("stdout_total_lines") == 2
    assert streams.get("stderr_total_lines") == 1

    # Ensure we do not duplicate at the top-level.
    assert "stdout" not in shaped
    assert "stderr" not in shaped
