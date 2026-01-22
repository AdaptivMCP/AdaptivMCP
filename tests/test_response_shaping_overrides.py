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

    # The server no longer wraps results into a separate summary/streams envelope.
    assert isinstance(shaped.get("result"), dict)
    assert shaped["result"].get("stdout") == "hi\n"

    # No extra wrapper fields are added.
    assert shaped.get("summary") is None
    assert shaped.get("streams") is None
    assert shaped.get("data") is None


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

    # In raw result mode, the payload is not truncated or re-shaped.
    assert "items" in shaped
    assert isinstance(shaped["items"], list) and len(shaped["items"]) == 5
    assert shaped.get("summary") is None
    assert shaped.get("data") is None


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

    # No stream truncation wrapper is applied; raw stdout remains in result.
    assert isinstance(shaped.get("result"), dict)
    assert shaped["result"].get("stdout") == "a\nb\nc\nd\ne\n"
    assert shaped.get("streams") is None


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

    # Raw result payload is preserved.
    assert set(shaped.keys()).issuperset({"status", "ok", "result"})
    assert isinstance(shaped.get("result"), dict)
    assert shaped["result"].get("stdout") == "hi\n"

    # No extra wrapper fields are added.
    assert shaped.get("summary") is None
    assert shaped.get("data") is None
    assert shaped.get("streams") is None
