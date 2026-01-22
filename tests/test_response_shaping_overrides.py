from __future__ import annotations

import github_mcp.mcp_server.decorators as dec

_chatgpt_friendly_result = dec._chatgpt_friendly_result


def _enable_shaping(monkeypatch):
    # The implementation disables response shaping under pytest for safety.
    # For these unit tests we explicitly enable the shaping path.
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)


def test_response_mode_override_enables_chatgpt_shaping(monkeypatch):
    _enable_shaping(monkeypatch)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "raw")

    payload = {
        "status": "ok",
        "ok": True,
        "result": {"exit_code": 0, "timed_out": False, "stdout": "hi\n"},
    }

    shaped = _chatgpt_friendly_result(payload, req={"response_mode": "chatgpt"})
    assert isinstance(shaped, dict)
    assert shaped.get("status") in {"success", "ok"}
    assert shaped.get("ok") is True

    report = shaped.get("report")
    assert isinstance(report, dict)
    assert isinstance(report.get("summary"), str) and report.get("summary")

    streams = report.get("streams")
    assert isinstance(streams, dict)
    assert streams.get("stdout") == "hi\n"

    # Avoid duplication of nested envelopes at the top-level.
    assert "result" not in shaped
    assert "stdout" not in shaped


def test_shaped_payload_does_not_echo_large_lists(monkeypatch):
    _enable_shaping(monkeypatch)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "raw")

    payload = {
        "status": "ok",
        "ok": True,
        "items": [{"n": i} for i in range(5)],
    }

    shaped = _chatgpt_friendly_result(
        payload,
        req={
            "chatgpt": {
                "response_mode": "chatgpt",
                "response_max_list_items": 2,
            }
        },
    )

    assert "items" not in shaped
    report = shaped.get("report")
    assert isinstance(report, dict)
    assert "items" not in report
    snap = report.get("snapshot")
    assert isinstance(snap, dict)
    assert snap.get("type") == "dict"


def test_stream_limits_clip_raw_stdout(monkeypatch):
    _enable_shaping(monkeypatch)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "raw")

    payload = {
        "status": "ok",
        "ok": True,
        "result": {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "a\nb\nc\nd\ne\n",
        },
    }

    shaped = _chatgpt_friendly_result(
        payload,
        req={
            "chatgpt": {
                "response_mode": "chatgpt",
                "response_stream_max_lines": 2,
                "response_stream_max_chars": 10_000,
            }
        },
    )

    report = shaped.get("report")
    assert isinstance(report, dict)
    streams = report.get("streams")
    assert isinstance(streams, dict)
    assert streams.get("stdout_truncated") is True
    assert streams.get("stdout_total_lines") == 5
    assert isinstance(streams.get("stdout"), str)
    assert "… (" in streams["stdout"]


def test_redaction_can_be_disabled_per_request_when_allowed(monkeypatch):
    _enable_shaping(monkeypatch)
    monkeypatch.setattr(dec, "REDACT_TOOL_OUTPUTS", True)
    monkeypatch.setattr(dec, "REDACT_TOOL_OUTPUTS_ALLOW_OVERRIDE", True)

    assert dec._effective_redact_tool_outputs({"chatgpt": {"redact_tool_outputs": False}}) is False
    assert dec._effective_redact_tool_outputs({"chatgpt": {"redact_tool_outputs": True}}) is True


def test_chatgpt_shaping_returns_single_structured_report_without_duplication(monkeypatch):
    _enable_shaping(monkeypatch)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "raw")

    payload = {
        "status": "ok",
        "ok": True,
        "ref": "main",
        "result": {"exit_code": 0, "timed_out": False, "stdout": "hi\n"},
    }

    shaped = _chatgpt_friendly_result(payload, req={"response_mode": "chatgpt"})
    assert isinstance(shaped, dict)
    assert set(shaped.keys()).issuperset({"status", "ok", "report"})

    # The top-level should be minimal (no nested envelopes or secondary summary strings).
    assert "result" not in shaped
    assert "summary" not in shaped
    assert "summary_text" not in shaped
    assert "stdout" not in shaped
    assert "stderr" not in shaped

    report = shaped.get("report")
    assert isinstance(report, dict)
    assert isinstance(report.get("summary"), str) and report.get("summary")
    assert isinstance(report.get("snapshot"), dict)
