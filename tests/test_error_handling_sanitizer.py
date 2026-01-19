import importlib


def test_sanitize_debug_value_does_not_over_redact_high_entropy(monkeypatch):
    # Ensure default threshold isn't artificially small.
    monkeypatch.delenv("GITHUB_MCP_ERROR_DEBUG_TRUNCATE_CHARS", raising=False)

    import github_mcp.mcp_server.error_handling as eh

    # 64-char high-entropy-looking string should NOT be redacted when it is not
    # associated with a secret-bearing key.
    v = "a" * 64
    out = eh._sanitize_debug_value({"sha": v})
    assert out["sha"] == v


def test_sanitize_debug_value_redacts_when_key_is_secret(monkeypatch):
    monkeypatch.delenv("GITHUB_MCP_ERROR_DEBUG_TRUNCATE_CHARS", raising=False)

    import github_mcp.mcp_server.error_handling as eh

    v = "a" * 64
    out = eh._sanitize_debug_value({"token": v})
    assert isinstance(out["token"], str)
    assert out["token"].startswith("<REDACTED_VALUE")


def test_sanitize_debug_value_truncates_very_long_strings(monkeypatch):
    # The implementation enforces a safety floor of 200 chars for operator
    # debugging, so set the env var to the minimum and exceed it.
    monkeypatch.setenv("GITHUB_MCP_ERROR_DEBUG_TRUNCATE_CHARS", "200")

    import github_mcp.mcp_server.error_handling as eh

    # Reload so the env var takes effect.
    eh = importlib.reload(eh)

    v = "x" * 500
    out = eh._sanitize_debug_value({"message": v})
    assert isinstance(out["message"], str)
    assert out["message"].startswith("<TRUNCATED_TEXT")
