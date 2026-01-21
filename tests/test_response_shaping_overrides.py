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
    # Shaped responses include a summary field.
    assert "summary" in shaped
    # stdout surfaces at the top level.
    assert shaped.get("stdout") == "hi\n"


def test_request_max_list_items_truncates_common_lists(monkeypatch):
    _enable_shaping(monkeypatch)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "raw")
    monkeypatch.setattr(dec, "CHATGPT_RESPONSE_MAX_LIST_ITEMS", 0)

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

    assert shaped.get("items_total") == 5
    assert shaped.get("items_truncated") is True
    assert isinstance(shaped.get("items"), list)
    assert len(shaped["items"]) == 2


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

    assert shaped.get("stdout_truncated") is True
    assert shaped.get("stdout_total_lines") == 5
    assert isinstance(shaped.get("stdout"), str)
    assert "… (" in shaped["stdout"]


def test_redaction_can_be_disabled_per_request_when_allowed(monkeypatch):
    _enable_shaping(monkeypatch)
    monkeypatch.setattr(dec, "REDACT_TOOL_OUTPUTS", True)
    monkeypatch.setattr(dec, "REDACT_TOOL_OUTPUTS_ALLOW_OVERRIDE", True)

    assert dec._effective_redact_tool_outputs({"chatgpt": {"redact_tool_outputs": False}}) is False
    assert dec._effective_redact_tool_outputs({"chatgpt": {"redact_tool_outputs": True}}) is True

