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
    assert shaped["ok"] is False


def test_mcp_tool_error_is_shaped_and_includes_tool_metadata(monkeypatch):
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
    tool_meta = shaped.get("tool_metadata")
    assert isinstance(tool_meta, dict)
    assert tool_meta.get("effective_write_action") is False

