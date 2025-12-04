import logging
from typing import Dict, Any

import pytest

import main


@pytest.fixture(autouse=True)
def _enable_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force WRITE_ALLOWED on so write tools can execute in tests.

    This avoids depending on authorize_write_actions inside the tests while
    still exercising the normal write-gated code paths.
    """

    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)


@pytest.mark.asyncio
async def test_apply_patch_and_commit_logging_shape(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify that apply_patch_and_commit emits the expected logging fields.

    The test does not hit the real GitHub API. Instead it monkeypatches the
    helpers used by apply_patch_and_commit so the tool completes
    successfully without network access.
    """

    # Minimal original and patched content.
    original_text = "line1\n"
    patched_text = "line1-updated\n"
    patch = ("--- a/file.txt\n"
             "+++ b/file.txt\n"
             "@@ -1 +1 @@\n"
             "-line1\n"
             "+line1-updated\n")

    # Stub helpers to avoid GitHub network calls.
    async def fake_decode(full_name: str, path: str, ref: str) -> Dict[str, Any]:  # type: ignore[override]
        assert full_name == "Proofgate-Revocations/chatgpt-mcp-github"
        assert path == "file.txt"
        return {"text": original_text, "sha": "sha-before"}

    async def fake_commit(
        full_name: str,
        path: str,
        message: str,
        body_bytes: bytes,
        branch: str,
        sha: str,
    ) -> Dict[str, Any]:  # type: ignore[override]
        assert full_name == "Proofgate-Revocations/chatgpt-mcp-github"
        assert path == "file.txt"
        assert sha == "sha-before"
        return {"content": {"sha": "sha-after"}, "commit": {}}

    async def fake_get_file(full_name: str, path: str, ref: str) -> Dict[str, Any]:  # type: ignore[override]
        assert full_name == "Proofgate-Revocations/chatgpt-mcp-github"
        assert path == "file.txt"
        return {"text": patched_text, "sha": "sha-after"}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main, "get_file_contents", fake_get_file)

    caplog.set_level(logging.INFO, logger="github_mcp.tools")

    with caplog.at_level(logging.INFO, logger="github_mcp.tools"):
        result = await main.apply_patch_and_commit(  # type: ignore[arg-type]
            full_name="Proofgate-Revocations/chatgpt-mcp-github",
            path="file.txt",
            patch=patch,
            branch="issue-145-logging-observability-v2",
            message="Test commit",
            return_diff=False,
        )

    assert result["status"] == "committed"

    start_records = [r for r in caplog.records if r.message == "tool_call_start"]
    success_records = [r for r in caplog.records if r.message == "tool_call_success"]

    assert start_records, caplog.text
    assert success_records, caplog.text

    start = start_records[-1]
    success = success_records[-1]

    assert start.tool_name == "apply_patch_and_commit"
    assert success.tool_name == "apply_patch_and_commit"
    assert start.call_id == success.call_id
    assert success.status == "ok"
    assert isinstance(success.duration_ms, int) and success.duration_ms >= 0
    assert success.write_action is True
    assert "write" in success.tags
    assert success.repo == "Proofgate-Revocations/chatgpt-mcp-github"
    assert success.path == "file.txt"
    assert "patch" in success.arg_keys
