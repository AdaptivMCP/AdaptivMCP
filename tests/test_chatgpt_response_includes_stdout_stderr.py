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

    # Raw payload is preserved.
    assert shaped.get("status") == "ok"
    assert shaped.get("ok") is True
    assert isinstance(shaped.get("result"), dict)
    assert shaped["result"].get("stdout") == "hello\nworld\n"
    assert shaped["result"].get("stderr") == "warn: nope\n"

    # Colored previews are injected at top-level.
    assert isinstance(shaped.get("stdout_colored"), str) and shaped["stdout_colored"]
    assert isinstance(shaped.get("stderr_colored"), str) and shaped["stderr_colored"]

    # No extra wrapper fields are added.
    assert shaped.get("streams") is None
    assert shaped.get("summary") is None
    assert shaped.get("data") is None
