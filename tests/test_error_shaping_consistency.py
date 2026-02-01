from __future__ import annotations


def test_chatgpt_friendly_result_overwrites_conflicting_ok(monkeypatch):
    import github_mcp.mcp_server.decorators as dec

    # The implementation disables response shaping under pytest for safety.
    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "chatgpt")

    payload = {
        "status": "error",
        "ok": True,  # conflicting signal
        "error": "nope",
    }

    shaped = dec._chatgpt_friendly_result(payload, req={"headers": {}})
    assert isinstance(shaped, dict)
    assert shaped["status"] == "error"
    # Compact shaping preserves raw tool payloads; it does not normalize ok/status.
    assert shaped["ok"] is True


def test_mcp_tool_error_is_shaped_without_gating(monkeypatch):
    import github_mcp.mcp_server.decorators as dec

    monkeypatch.setattr(dec, "_running_under_pytest", lambda: False)
    monkeypatch.setattr(dec, "RESPONSE_MODE_DEFAULT", "chatgpt")
    monkeypatch.setattr(dec, "_should_enforce_write_gate", lambda _req: False)

    @dec.mcp_tool(name="boom_tool", write_action=False)
    def boom_tool() -> dict[str, object]:
        raise ValueError("boom")

    shaped = boom_tool()
    assert isinstance(shaped, dict)
    assert shaped.get("status") == "error"
    assert shaped.get("ok") is False
    # Invocation metadata is not merged for chatgpt/compact modes, but structured
    # errors may still include gating when produced by the error formatter.
    assert isinstance(shaped.get("gating"), dict)
