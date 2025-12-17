import pytest


@pytest.mark.asyncio
async def test_perform_github_commit_refreshes_workspace(monkeypatch):
    import main

    calls = {"commit": None, "refresh": None}

    async def fake_commit(*, full_name, path, message, branch, body_bytes, sha):
        calls["commit"] = {
            "full_name": full_name,
            "path": path,
            "message": message,
            "branch": branch,
            "body_bytes": body_bytes,
            "sha": sha,
        }
        return {"ok": True}

    async def fake_ensure_workspace_clone(
        *, full_name=None, ref="main", reset=False, owner=None, repo=None, branch=None
    ):
        calls["refresh"] = {
            "full_name": full_name,
            "ref": ref,
            "reset": reset,
            "owner": owner,
            "repo": repo,
            "branch": branch,
        }
        return {"repo_dir": "/tmp/repo", "branch": ref, "reset": reset}

    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main, "ensure_workspace_clone", fake_ensure_workspace_clone)

    result = await main._perform_github_commit_and_refresh_workspace(
        full_name="owner/repo",
        path="foo.txt",
        message="msg",
        branch="feature-branch",
        body_bytes=b"data",
        sha="sha123",
    )

    assert result == {"ok": True}
    assert calls["commit"] is not None
    assert calls["refresh"] is not None
    assert calls["refresh"]["full_name"] == "owner/repo"
    assert calls["refresh"]["ref"] == "feature-branch"
    assert calls["refresh"]["reset"] is True
