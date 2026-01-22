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

    # The server no longer wraps results into a separate summary/streams envelope.
    # Stdout/stderr remain in the tool's raw payload.
    assert shaped.get("status") in {"success", "ok"}
    assert shaped.get("ok") is True
    assert isinstance(shaped.get("result"), dict)
    assert shaped["result"].get("stdout") == "hello\nworld\n"
    assert shaped["result"].get("stderr") == "warn: nope\n"

    # No extra wrapper fields are added.
    assert shaped.get("streams") is None
    assert shaped.get("summary") is None
    assert shaped.get("data") is None
