import pytest


def test_log_preview_does_not_truncate(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.mcp_server import schemas

    monkeypatch.setenv("GITHUB_MCP_LOG_PREVIEW_MAX_CHARS", "10")
    out = schemas._truncate_str("x" * 200)

    assert out == "x" * 200
