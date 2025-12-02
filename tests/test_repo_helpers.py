import pytest

import main
import extra_tools


@pytest.mark.asyncio
async def test_move_file_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    calls: dict[str, object] = {}

    async def fake_decode(full_name: str, path: str, ref: str):
        calls["decode_args"] = (full_name, path, ref)
        return {"text": "hello"}

    async def fake_apply_text_update_and_commit(**kwargs):
        calls["apply_args"] = kwargs
        return {"commit": {"sha": "abc123"}}

    async def fake_delete_file(**kwargs):
        calls["delete_args"] = kwargs
        return {"commit": {"sha": "def456"}}

    def fake_ensure_write_allowed(context: str) -> None:
        calls["write_context"] = context

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "apply_text_update_and_commit", fake_apply_text_update_and_commit)
    monkeypatch.setattr(extra_tools, "delete_file", fake_delete_file)
    monkeypatch.setattr(main, "_ensure_write_allowed", fake_ensure_write_allowed)

    result = await main.move_file(
        full_name="owner/repo",
        from_path="old/path.py",
        to_path="new/path.py",
        branch="feature",
        message="Move file",
    )

    assert calls["decode_args"] == ("owner/repo", "old/path.py", "feature")
    assert calls["apply_args"]["full_name"] == "owner/repo"
    assert calls["apply_args"]["path"] == "new/path.py"
    assert calls["apply_args"]["branch"] == "feature"
    assert calls["delete_args"]["path"] == "old/path.py"
    assert calls["delete_args"]["branch"] == "feature"
    assert "move_file from old/path.py to new/path.py in owner/repo" in calls["write_context"]
    assert result["status"] == "moved"
