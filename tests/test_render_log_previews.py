from __future__ import annotations

import pytest


def test_log_preview_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.mcp_server import schemas

    monkeypatch.setenv("GITHUB_MCP_LOG_PREVIEW_MAX_CHARS", "10")
    out = schemas._truncate_str("x" * 200)

    # Enforced minimum of 128 chars.
    assert len(out) == 128
    assert out.endswith("…")
