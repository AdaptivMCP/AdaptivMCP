def test_sanitize_for_logs_honors_max_depth(monkeypatch):
    # Force compact mode.
    monkeypatch.delenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", raising=False)
    monkeypatch.setenv("ADAPTIV_MCP_LOG_MAX_DEPTH", "1")

    from github_mcp import config

    out = config._sanitize_for_logs({"a": {"b": {"c": 1}}})
    assert isinstance(out, dict)
    # At max depth, nested payloads collapse to a string representation.
    assert isinstance(out["a"], str)
    assert out["a"].startswith("{")


def test_sanitize_for_logs_honors_max_list(monkeypatch):
    monkeypatch.delenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", raising=False)
    monkeypatch.setenv("ADAPTIV_MCP_LOG_MAX_LIST", "1")

    from github_mcp import config

    out = config._sanitize_for_logs([1, 2, 3])
    assert out == [1, "… (2 more)"]


def test_sanitize_for_logs_truncates_large_mappings(monkeypatch):
    monkeypatch.delenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", raising=False)

    from github_mcp import config

    payload = {f"k{i}": i for i in range(205)}
    out = config._sanitize_for_logs(payload)
    assert isinstance(out, dict)
    # When more than 200 keys exist, sanitizer appends an ellipsis marker.
    assert "…" in out


def test_sanitize_for_logs_full_fidelity_preserves_jsonable(monkeypatch):
    monkeypatch.setenv("ADAPTIV_MCP_LOG_FULL_FIDELITY", "1")

    from github_mcp import config

    out = config._sanitize_for_logs({"body": b"hello\nworld"})
    assert out == {"body": "hello\nworld"}


def test_shorten_token_uuid(monkeypatch):
    monkeypatch.setenv("ADAPTIV_MCP_SHORTEN_TOKENS", "1")

    from github_mcp import config

    uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert config.shorten_token(uuid) == "123e4567"


def test_shorten_token_short_values_unchanged(monkeypatch):
    monkeypatch.setenv("ADAPTIV_MCP_SHORTEN_TOKENS", "1")

    from github_mcp import config

    # Shorter than head+tail+2 => unchanged.
    assert config.shorten_token("abc") == "abc"
