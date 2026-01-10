from __future__ import annotations

import pytest


def test_log_preview_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.mcp_server import schemas

    monkeypatch.setenv("GITHUB_MCP_LOG_PREVIEW_MAX_CHARS", "10")
    out = schemas._truncate_str("x" * 200)

    # Enforced minimum of 128 chars.
    assert len(out) == 128
    assert out.endswith("…")


def test_tool_args_preview_redacts_secret_keys() -> None:
    from github_mcp.mcp_server import schemas

    args = {
        "token": "supersecret",
        "nested": {"authorization": "supersecret"},
        "safe": "ok",
    }

    preview = schemas._format_tool_args_preview(args)

    assert "<redacted>" in preview
    assert "supersecret" not in preview
    assert "ok" in preview


def test_preflight_tool_args_redacts_and_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.mcp_server import schemas

    monkeypatch.setenv("GITHUB_MCP_LOG_PREVIEW_MAX_CHARS", "128")
    out = schemas._preflight_tool_args(
        "demo_tool",
        {"token": "supersecret", "huge": "x" * 5000},
        compact=True,
    )

    assert out["tool"] == "demo_tool"
    assert isinstance(out.get("preview"), str)

    preview = out["preview"]
    assert "supersecret" not in preview
    assert "<redacted>" in preview

    # Ensure the preview is bounded.
    assert len(preview) <= 128
