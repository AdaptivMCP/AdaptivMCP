from typing import Any, Dict

import pytest

import main

import github_mcp.config as config


@pytest.fixture(autouse=True)
def _enable_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force WRITE_ALLOWED on so write tools can execute in tests."""

    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)


@pytest.mark.asyncio
async def test_apply_text_update_and_commit_logging_shape(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify that apply_text_update_and_commit emits the expected logging fields.

    The test does not hit the real GitHub API. Instead it monkeypatches the
    helpers used by apply_text_update_and_commit so the tool completes
    successfully without network access.
    """

    original_text = "line1\n"
    updated_text = "line1-updated\n"

    call_count = {"n": 0}

    async def fake_decode(full_name: str, path: str, ref: str) -> Dict[str, Any]:  # type: ignore[override]
        assert full_name == "Proofgate-Revocations/chatgpt-mcp-github"
        assert path == "file.txt"
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"text": original_text, "sha": "sha-before"}
        return {"text": updated_text, "sha": "sha-after"}

    async def fake_commit(
        full_name: str,
        path: str,
        message: str,
        body_bytes: bytes,
        branch: str,
        sha: str | None,
    ) -> Dict[str, Any]:  # type: ignore[override]
        assert full_name == "Proofgate-Revocations/chatgpt-mcp-github"
        assert path == "file.txt"
        assert sha == "sha-before"
        assert body_bytes == updated_text.encode("utf-8")
        return {"content": {"sha": "sha-after"}, "commit": {}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)

    caplog.set_level(config.DETAILED_LEVEL, logger="github_mcp.tools")

    with caplog.at_level(config.DETAILED_LEVEL, logger="github_mcp.tools"):
        result = await main.apply_text_update_and_commit(
            full_name="Proofgate-Revocations/chatgpt-mcp-github",
            path="file.txt",
            updated_content=updated_text,
            branch="issue-145-logging-observability-v2",
            message="Test commit",
            return_diff=False,
        )

    assert result["status"] == "committed"

    start_records = [r for r in caplog.records if getattr(r, "event", None) == "tool_call_start"]
    success_records = [
        r for r in caplog.records if getattr(r, "event", None) == "tool_call_success"
    ]

    assert start_records, caplog.text
    assert success_records, caplog.text

    start = start_records[-1]
    success = success_records[-1]

    assert start.tool_name == "apply_text_update_and_commit"
    assert success.tool_name == "apply_text_update_and_commit"
    assert start.call_id == success.call_id
    assert success.status == "ok"
    assert "args=" in start.message
    assert isinstance(success.duration_ms, int) and success.duration_ms >= 0
    assert success.write_action is True
    assert "write" in success.tags
    assert success.repo == "Proofgate-Revocations/chatgpt-mcp-github"
    assert success.path == "file.txt"
    assert "updated_content" in success.arg_keys
