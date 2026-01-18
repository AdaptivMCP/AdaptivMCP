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

    # Raw surfaces.
    assert shaped.get("stdout") == "hello\nworld\n"
    assert shaped.get("stderr") == "warn: nope\n"

    # Colored previews.
    sc = shaped.get("stdout_colored")
    ec = shaped.get("stderr_colored")
    assert isinstance(sc, str) and "stdout" in sc
    assert isinstance(ec, str) and "stderr" in ec
    # Should include ANSI escape sequences.
    assert "\x1b[" in sc
    assert "\x1b[" in ec

